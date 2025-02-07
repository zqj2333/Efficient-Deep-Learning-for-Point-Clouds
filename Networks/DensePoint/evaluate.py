import torch
import torch.optim as optim
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.autograd import Variable
import torch.nn.functional as F
import numpy as np
import os
from torchvision import transforms
from models import DensePointCls_L6 as DensePoint
from data import ModelNet40Cls
import utils.pytorch_utils as pt_utils
import utils.pointnet2_utils as pointnet2_utils
import data.data_utils as d_utils
import argparse
import random
import yaml
import time

torch.backends.cudnn.enabled = True
torch.backends.cudnn.benchmark = True
torch.backends.cudnn.deterministic = True

seed = 123
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)            
torch.cuda.manual_seed(seed)       
torch.cuda.manual_seed_all(seed)   

parser = argparse.ArgumentParser(description='DensePoint Shape Classification Voting Evaluate')
parser.add_argument('--config', default='cfgs/config_cls.yaml', type=str)

NUM_REPEAT = 300
NUM_VOTE = 10

def main():
    args = parser.parse_args()
    with open(args.config) as f:
        config = yaml.load(f)
    for k, v in config['common'].items():
        setattr(args, k, v)
    
    test_transforms = transforms.Compose([
        d_utils.PointcloudToTensor()
    ])

    test_dataset = ModelNet40Cls(num_points = args.num_points, root = args.data_root, transforms=test_transforms, train=False)
    test_dataloader = DataLoader(
        test_dataset, 
        batch_size=args.batch_size,
        shuffle=False, 
        num_workers=int(args.workers), 
        pin_memory=True
    )
    
    model = DensePoint(num_classes = args.num_classes, input_channels = args.input_channels, use_xyz = True)
    model.cuda()
    
    if args.checkpoint is not '':
        model.load_state_dict(torch.load(args.checkpoint))
        print('Load model successfully: %s' % (args.checkpoint))
    
    # evaluate
    PointcloudScale = d_utils.PointcloudScale()   # initialize random scaling
    model.eval()
    global_acc = 0
    for i in range(NUM_REPEAT):
        preds = []
        labels = []

        s = time.time()
        for j, data in enumerate(test_dataloader, 0):
            points, target = data
            points, target = points.cuda(), target.cuda()
            points, target = Variable(points, volatile=True), Variable(target, volatile=True)
            # points [batch_size, num_points, dimensions], e.g., [256, 2048, 3]

            # furthest point sampling
            # fps_idx = pointnet2_utils.furthest_point_sample(points, 1200)  # (B, npoint)

            # random sampling
            fps_idx = np.random.randint(0, points.shape[1]-1, size=[points.shape[0], 1200])
            fps_idx = torch.from_numpy(fps_idx).type(torch.IntTensor).cuda()

            pred = 0
            for v in range(NUM_VOTE):
                new_fps_idx = fps_idx[:, np.random.choice(1200, args.num_points, False)]
                new_points = pointnet2_utils.gather_operation(points.transpose(1, 2).contiguous(), new_fps_idx).transpose(1, 2).contiguous()
                if v > 0:
                    new_points.data = PointcloudScale(new_points.data)
                pred += F.softmax(model(new_points), dim = 1)
            pred /= NUM_VOTE
            target = target.view(-1)
            _, pred_choice = torch.max(pred.data, -1)

            preds.append(pred_choice)
            labels.append(target.data)
        e = time.time()

        preds = torch.cat(preds, 0)
        labels = torch.cat(labels, 0)
        acc = (preds == labels).sum() / labels.numel()
        if acc > global_acc:
            global_acc = acc
        print('Repeat %3d \t Acc: %0.6f' % (i + 1, acc))
        print('time (secs) for 1 epoch: ', (e - s))
    print('\nBest voting acc: %0.6f' % (global_acc))
        
if __name__ == '__main__':
    main()
