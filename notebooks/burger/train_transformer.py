#!/bin/bash python
import torch 
from torch.utils import tensorboard
import torch.optim as optim
import time
import os
import ray
from ray import tune
from ray.tune.schedulers import AsyncHyperBandScheduler, ASHAScheduler
from transformer import Tranformer
from utils import *



def evaluate(model,data_loader,criterion):
    model.eval()
    total_loss = 0.
    rmse = 0.
    device = "cpu"
    if torch.cuda.is_available():
        device = "cuda:0"
        if torch.cuda.device_count() > 1:
            model = nn.DataParallel(model)
    for (data,targets) in data_loader:
        data, targets = data.to(device), targets.to(device)
        output = model(data, targets)
        total_loss += criterion(output, targets).detach().cpu().numpy()
    return total_loss

def train(config, checkpoint_dir):
    train_proportion = 0.75
    test_proportion = 0.1
    val_proportion = 0.15
    feature_size = config['feature_size']
    num_enc_layers = config['num_enc_layers']
    num_dec_layers = config['num_dec_layers']
    num_head = config['num_head']
    dropout = config['dropout']
    d_ff = config['d_ff']
    lr = 1e-5#config['lr']
    #d_ff = 512
    window_size = 10#config['window_size']
    batch_size = 16#config['batch_size']
    
    #model = Tranformer(feature_size=feature_size,num_layers=num_layer,dropout=dropout,num_head=num_head)
    model = Tranformer(feature_size=feature_size,num_enc_layers=num_enc_layers,num_dec_layers = num_dec_layers,\
            d_ff = d_ff, dropout=dropout,num_head=num_head)
    device = "cpu"
    if torch.cuda.is_available():
        device = "cuda:0"
        if torch.cuda.device_count() > 1:
            model = nn.DataParallel(model)
    model.to(device)
    epochs = 10        
    criterion = nn.MSELoss() ######MAELoss()
    optimizer = optim.AdamW(model.parameters(), lr=lr)
    scheduler = optim.lr_scheduler.StepLR(optimizer, 1.0, gamma=0.95)
    writer = tensorboard.SummaryWriter('./test_logs')
    
    # if checkpoint_dir:
    #     checkpoint = os.path.join(checkpoint_dir, "checkpoint")
    #     model_state, optimizer_state = torch.load(checkpoint)
    #     model.load_state_dict(model_state)
    #     optimizer.load_state_dict(optimizer_state)
        
    train_loader,val_loader, test_loader = get_data_loaders(train_proportion, test_proportion, val_proportion,\
         window_size=window_size, pred_size =1, batch_size=batch_size, num_workers = 2, pin_memory = False)

    for epoch in range(1, epochs + 1):
        model.train() 
        total_loss = 0.

        for i, (data, targets) in enumerate(train_loader):
            data, targets = data.to(device), targets.to(device)
            optimizer.zero_grad()
            output = model(data, targets) 
            loss = criterion(output, targets)
            total_loss += loss.item()
            loss.backward()
            optimizer.step()
            
        val_loss = evaluate(model, val_loader, criterion)
        print(f'Epoch: {epoch}, train_loss: {total_loss}, val_loss: {val_loss}')
        
        writer.add_scalar('train_loss',total_loss,epoch)
        writer.add_scalar('val_loss',val_loss,epoch)
        
        tune.report(val_loss=val_loss)
        scheduler.step() 


if __name__ == "__main__":
    config = {
        # 'feature_size':tune.grid_search([16,32,64,128]),
        # 'num_enc_layers':tune.grid_search([1,2]),
        # 'num_dec_layers':tune.grid_search([1,2]),
        # 'num_head':tune.grid_search([2,4,8]),
        # 'dropout':tune.grid_search([0.1,0.2]),
        # 'd_ff':tune.grid_search([512])
        'feature_size':tune.grid_search([16]),
        'num_enc_layers':tune.grid_search([1]),
        'num_dec_layers':tune.grid_search([1]),
        'num_head':tune.grid_search([2]),
        'dropout':tune.grid_search([0.1]),
        'd_ff':tune.grid_search([512])
        #'lr':tune.grid_search([0.0001]),
        #'window_size':tune.grid_search([12,36,108,324]),
        #'batch_size':tune.grid_search([16])
}
    ray.init(ignore_reinit_error=False)
    sched = ASHAScheduler(
            max_t=200,
            grace_period=20,
            reduction_factor=2)
    analysis = tune.run(tune.with_parameters(train), config=config, metric='val_loss', mode='min',\
         scheduler=sched, resources_per_trial={"cpu": 32,"gpu": 4},local_dir="/scratch/tl2204/ray_results",)

    best_trail = analysis.get_best_config(mode='min')
    print('The best configs are: ',best_trail)
    ray.shutdown()