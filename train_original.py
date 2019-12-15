'''Train CIFAR10 with PyTorch.'''
import sys
sys.path.insert(0,'..')
import torch
import torch.nn as nn
import torch.optim as optim
import torch.backends.cudnn as cudnn

from datasets import get_dataset


import tensorboardX
import time
import argparse
import numpy as np
import GPUtil, os
import re

np.set_printoptions(3)

parser = argparse.ArgumentParser(description='PyTorch CIFAR Training')
parser.add_argument('--base_lr', default=0.05, type=float, help='learning rate')
parser.add_argument('--resume', '-r', default=None, help='resume from checkpoint')
parser.add_argument('--batch_size', default=128,type=int)
parser.add_argument('--test_batch_size', default=512,type=int)
parser.add_argument('--config_name',default='vgg16')
parser.add_argument('--actions',default='',type=str)
parser.add_argument('--epochs',default=90,type=int)
parser.add_argument('--parallel',default=False)
parser.add_argument('--weight_decay',default=5e-4,type=float)
parser.add_argument('--half',default=0,type=bool)
parser.add_argument('--scale',default=-1,type=float)
parser.add_argument('--gpu',default=-1,type=int)

args = parser.parse_args()
args.dataset='CIFAR100' if '100' in args.config_name else 'CIFAR10'

print(args)

if not args.parallel:
    if args.gpu==-1:
        min_mem_gpu = np.argmin([_.memoryUsed for _ in GPUtil.getGPUs()])
        print("selecting GPU {}".format(min_mem_gpu))
        os.environ['CUDA_VISIBLE_DEVICES'] = str(min_mem_gpu)
    else:
        os.environ['CUDA_VISIBLE_DEVICES'] = str(args.gpu)

device = 'cuda' if torch.cuda.is_available() else 'cpu'

# Data
testloader,valloader,trainloader,trainvalloader=get_dataset(args)
classes = ('plane', 'car', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck')

# Model
print('==> Building model..')

config_name=args.config_name

# build network

from build_network import get_net_by_name
net=get_net_by_name(config_name)

model_name=config_name
log_name=f'/{model_name}_original_e{args.epochs}'
writer=tensorboardX.SummaryWriter(f'log/{log_name}')


if device == 'cuda':
    net=net.cuda()
    if args.parallel:
        net = nn.DataParallel(net)
    cudnn.benchmark = True

if args.resume:
    import utils.loader
    # Load checkpoint.
    net.load_state_dict(torch.load(args.resume))
    # utils.loader.load_pretrained(net,args.resume)

criterion = nn.CrossEntropyLoss()
is_warm_up=True if 'resnet110' in config_name else False
optimizer=torch.optim.SGD(net.parameters(),args.base_lr,0.9,weight_decay=args.weight_decay)
# lr_scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,args.epochs,1e-5)
lr_scheduler=torch.optim.lr_scheduler.MultiStepLR(optimizer,[int(args.epochs*0.5),int(args.epochs*0.75)],0.1)


def train(epoch):
    print('\nEpoch: %d' % epoch)
    net.train()
    train_loss = 0
    correct = 0
    total = 0
    for batch_idx, (inputs, targets) in enumerate(trainloader):
        inputs, targets = inputs.to(device), targets.to(device)
        optimizer.zero_grad()
        outputs = net(inputs)
        loss = criterion(outputs, targets)
        loss.backward()
        optimizer.step()

        train_loss += loss.item()
        _, predicted = outputs.max(1)
        total += targets.size(0)
        correct += predicted.eq(targets).sum().item()
        if batch_idx%60==59:
            print(batch_idx, len(trainloader), 'Loss: %.3f | Acc: %.3f%% (%d/%d)'
                % (train_loss/(batch_idx+1), 100.*correct/total, correct, total))

best_acc=0
def test(epoch):
    global best_acc
    net.eval()
    test_loss = 0
    correct = 0
    total = 0
    with torch.no_grad():
        for batch_idx, (inputs, targets) in enumerate(testloader):
            inputs, targets = inputs.to(device), targets.to(device)
            outputs = net(inputs)
            loss = criterion(outputs, targets)

            test_loss += loss.item()
            _, predicted = outputs.max(1)
            total += targets.size(0)
            correct += predicted.eq(targets).sum().item()
    print(batch_idx, len(testloader), 'Loss: %.3f | Acc: %.3f%% (%d/%d)'
        % (test_loss/(batch_idx+1), 100.*correct/total, correct, total))

    # Save checkpoint.
    acc = 100.*correct/total
    if acc > best_acc:
        print("save best acc",acc)
        torch.save(net.state_dict(),'checkpoint/{}.pth'.format(log_name))
        best_acc=acc

for epoch in range(0, args.epochs):
    train(epoch)
    lr_scheduler.step(epoch)
    test(epoch)
os.system('mv {} {}'.format('checkpoint/{}.pth'.format(log_name),
                            'checkpoint/{}_{:.3f}.pth'.format(log_name,best_acc)))