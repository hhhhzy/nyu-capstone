#!/bin/bash python
import torch 
from torch.utils import tensorboard
import torch.optim as optim
import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, explained_variance_score, r2_score
import matplotlib.pyplot as plt
import seaborn as sns
import time
import os
from transformer import Transformer
from utils import *

class early_stopping():
    def __init__(self, patience=5, delta=0):
        self.patience = patience
        self.delta = delta
        self.early_stop = False
        self.best_loss = None
        self.counter = 0
        self.best_model = None
    
    def __call__(self, model, val_loss):
        if self.best_loss is None:
            self.best_loss = val_loss
        elif val_loss < self.best_loss-self.delta:
            self.best_loss = val_loss
            self.counter = 0
            self.best_model = model
        else:
            self.counter += 1 
            if self.counter == self.patience:
                self.early_stop = True
                print('Early stopping')
            print(f'----Current loss {val_loss} higher than best loss {self.best_loss}, early stop counter {self.counter}----')

def process_one_batch(src, tgt, src_coord, tgt_coord, src_ts, tgt_ts, patch_size): 
    x1, x2, x3 = patch_size
    #dec_rollout = src[:,-x1*x2*x3:,:]
    dec_rollout = torch.zeros([tgt.shape[0], x1*x2*x3, tgt.shape[-1]]).float().to(device)
    for i in range(batch_size):
        for j in range(x1*x2*x3):
            dec_rollout[i,j,:] = torch.cat([tgt[i,j+x1*x2*x3*k,:] for k in range(window_size-1)], dim=0).mean()
    dec_in = torch.cat([src[:,x1*x2*x3:,:], dec_rollout], dim=1).float().to(device)
    outputs = model(src, dec_in, src_coord, tgt_coord, src_ts, tgt_ts)
    return outputs, tgt

def evaluate(model,data_loader,criterion, patch_size, predict_res = False):
    model.eval()    
    test_rollout = torch.Tensor(0)   
    test_result = torch.Tensor(0)  
    truth = torch.Tensor(0)
    total_loss = 0.
    x1, x2, x3 = patch_size
    device = "cpu"
    if torch.cuda.is_available():
        device = "cuda:0"
        if torch.cuda.device_count() > 1:
            model = nn.DataParallel(model)
    with torch.no_grad():        
        for i, ((src, tgt), (src_coord, tgt_coord), (src_ts, tgt_ts)) in enumerate(data_loader):
            src, tgt, src_coord, tgt_coord, src_ts, tgt_ts = src.to(device), tgt.to(device), \
                                                            src_coord.to(device), tgt_coord.to(device), src_ts.to(device), tgt_ts.to(device)
            # dec_inp = torch.zeros([tgt.shape[0], x1*x2*x3, tgt.shape[-1]]).float().to(device)
            # dec_inp = torch.cat([tgt[:,:-x1*x2*x3,:], dec_inp], dim=1).float().to(device)
            # output = model(src, dec_inp, src_coord, tgt_coord, src_ts, tgt_ts)
            output = model(src, tgt, src_coord, tgt_coord, src_ts, tgt_ts)
            total_loss += criterion(output[:,-x1*x2*x3:,:], tgt[:,-x1*x2*x3:,:]).detach().cpu().numpy()

    return total_loss

def predict_model(model, test_loader, epoch, config={},\
                    plot=True, plot_range=[0,0.01], final_prediction=False, predict_res = False):
    '''
    Note: 
        Don't forget to create a subfolder 'final_plot' under 'figs'
    parameters:
        plot_range: [a,b], 0<=a<b<=1, where a is the proportion that determines the start point to plot, b determines the end point. 
        final_prediction: True, if done with training and using the trained/saved model to predict the final result
        config: dictionary, the config of this plot, used for saving distinguishable plots for each trail
    '''
    model.eval()
    window_size = config['window_size']  
    test_result = torch.Tensor(0)
    test_rollout = {}#torch.Tensor(0) 
    truth = torch.Tensor(0) 
    test_ts = torch.Tensor(0)
    test_coord = torch.Tensor(0)
    device = "cpu"
    if torch.cuda.is_available():
        device = "cuda:0"
        if torch.cuda.device_count() > 1:
            model = nn.DataParallel(model)
    
    with torch.no_grad():
        for i, ((src, tgt), (src_coord, tgt_coord), (src_ts, tgt_ts)) in enumerate(test_loader):
            src, tgt, src_coord, tgt_coord, src_ts, tgt_ts = src.to(device), tgt.to(device), \
                                                            src_coord.to(device), tgt_coord.to(device), src_ts.to(device), tgt_ts.to(device)
            key_val = str(tgt_coord[0,0,:])
            if test_rollout.get(key_val) == None:
                enc_in = src
                dec_in = tgt
            else:
                enc_in = test_rollout[key_val][:,-tgt.shape[1]:,:].float()
                # dec_rollout = enc_in[:,-x1*x2*x3:,:].float()
                dec_rollout = torch.zeros([tgt.shape[0], x1*x2*x3, tgt.shape[-1]]).float().to(device)
                for j in range(x1*x2*x3):
                    dec_rollout[:,j,:] = torch.cat([enc_in[:,j+x1*x2*x3*k,:] for k in range(1, window_size)], dim=0).mean()
                dec_in = torch.cat([enc_in[:,x1*x2*x3:,:], dec_rollout], dim=1).float()

            output = model(enc_in, dec_in, src_coord, tgt_coord, src_ts, tgt_ts)
            test_rollout[key_val] = torch.cat([test_rollout.get(key_val, enc_in[:,x1*x2*x3:,:]),output[:,-x1*x2*x3:,:]], dim=1)
            test_ts = torch.cat((test_ts, tgt_ts[:,-x1*x2*x3:,:].flatten().detach().cpu()), 0)
            test_coord = torch.cat((test_coord, tgt_coord[:,-x1*x2*x3:,:].reshape(-1,3).detach().cpu()), 0)
            truth = torch.cat((truth, tgt[:,-x1*x2*x3:,:].flatten().detach().cpu()), 0)
            test_result = torch.cat((test_result, output[:,-x1*x2*x3:,:].flatten().detach().cpu()), 0)

        a = torch.cat([test_ts.unsqueeze(-1), test_coord, test_result.unsqueeze(-1), truth.unsqueeze(-1)], dim=-1)
        a = a.numpy()
        a = a[np.argsort(a[:, 3])]
        a = a[np.argsort(a[:, 2], kind='stable')]
        a = a[np.argsort(a[:, 1], kind='stable')]
        a = a[np.argsort(a[:, 0], kind='stable')]

        final_result = {'time': a[:,0], 'x1': a[:,1], 'x2': a[:,2], 'x3': a[:,3], 'prediction': a[:,4], 'truth':a[:,5]}
        
        if predict_res:
            residuals = pd.DataFrame.from_dict(final_result)
            truth = pd.read_csv('tune_results/data_original.csv',index_col=0)
            ### Group by time since last timestamp is duplicated
            #truth.time = np.round(truth.time.values,5)
            #residuals.time = np.round(residuals.time.values,5)
            #residuals = residuals.groupby(['time','x1','x2','x3']).mean().reset_index()
            #truth = truth.groupby(['time','x1','x2','x3']).mean().reset_index()

            ### Reconstruct predictions, truth is also reconstructed to validate answer
            pred_timestamps = residuals.time.unique()
            pred_start_time = residuals.time[0]
            pred_start_truth = truth[truth['time']==truth.time.unique()[-len(pred_timestamps)]]
            for i,(t1,t2) in enumerate(zip(pred_timestamps,truth.time.unique()[-len(pred_timestamps):])):
                truth_values = truth.loc[truth['time']==t2].truth_original.values
                pred_values = residuals.loc[residuals['time']==t1].prediction.values
                truth_check_values = residuals.loc[residuals['time']==t1].truth.values
                if i==0:
                    prev_truth_plus_residual = pred_values+truth_values
                else:
                    prev_truth_plus_residual = pred_values+prev_truth_plus_residual
                residuals.loc[residuals['time']==t1,'prediction']= prev_truth_plus_residual
                residuals.loc[residuals['time']==t1,'truth'] = truth_check_values+truth_values
            final_result = residuals

        if config['scale']==True:
            final_result['prediction'] = scaler.inverse_transform(final_result['prediction'])
            final_result['truth'] = scaler.inverse_transform(final_result['truth'])
    if plot==True:
        # plot a part of the result
        fig, ax = plt.subplots(nrows =1, ncols=1, figsize=(20,10))
        plot_start = int(len(final_result['prediction'])*plot_range[0])
        plot_end = int(len(final_result['prediction'])*plot_range[1])
        ax.plot(final_result['truth'][plot_start:plot_end],label = 'truth')
        ax.plot(final_result['prediction'][plot_start:plot_end],label='forecast')
        ax.plot(final_result['prediction'][plot_start:plot_end] - final_result['truth'][plot_start:plot_end],ls='--',label='residual')            
        #ax.grid(True, which='both')
        ax.axhline(y=0)
        ax.legend(loc="upper right")
        if final_prediction == True:
            fig.savefig(root_dir + '/figs/final_plot' + f"/range{plot_range}_pe{config['pe_type']}_batch{config['batch_size']}_window{config['window_size']}_patch{config['patch_size']}.png")
        else:
            fig.savefig(root_dir + '/figs/tmp_plot' + f"/pe{config['pe_type']}_batch{config['batch_size']}_window{config['window_size']}_patch{config['patch_size']}_epoch{epoch}.png")
            if epoch == config['epochs']:
                fig.savefig(root_dir + '/figs/final_plot'+ f"/range{plot_range}_pe{config['pe_type']}_batch{config['batch_size']}_window{config['window_size']}_patch{config['patch_size']}.png")
        plt.close(fig)
    if final_prediction == True:
        return final_result


  
    


if __name__ == "__main__":
    print(f'Pytorch version {torch.__version__}')
    root_dir = '/scratch/zh2095/nyu-capstone/yd_test/tune_results/'
    csv_path = '/scratch/zh2095/nyu-capstone/data/rho_original_16.csv'

    sns.set_style("whitegrid")
    sns.set_palette(['#57068c','#E31212','#01AD86'])
    plt.rcParams['animation.ffmpeg_path'] = '/ext3/conda/bootcamp/bin/ffmpeg'
  
    model_config = {'epochs':2,  'pe_type': '3d_temporal', 'batch_size': 16, 'feature_size': 144, 'num_enc_layers': 1, 'num_dec_layers': 4, \
                     'num_head': 4, 'd_ff': 512, 'dropout': 0.2, 'lr': 1e-5, 'lr_decay': 0.9, 'mask_type':'patch','decoder_only':False} 
    
    data_config = {'window_size': 10, 'option': 'patch', 'patch_size': (4,4,4), 'scale': True, 'add_noise': True, 'noise': (0,1e-2), 'predict_res': False}
    best_config = model_config
    best_config.update(data_config)

    # transformer parameters
    epochs = model_config['epochs']
    pe_type = model_config['pe_type']
    batch_size = model_config['batch_size']
    feature_size = model_config['feature_size']
    num_enc_layers = model_config['num_enc_layers']
    num_dec_layers = model_config['num_dec_layers']
    d_ff = model_config['d_ff']
    num_head = model_config['num_head']
    dropout = model_config['dropout']
    lr = model_config['lr']
    lr_decay = model_config['lr_decay']
    mask_type = model_config['mask_type']
    decoder_only = model_config['decoder_only']

    # dataset parameters
    train_proportion = 0.6
    test_proportion = 0.2
    val_proportion = 0.2
    grid_size = 16
    window_size = data_config['window_size']
    patch_size = data_config['patch_size']
    scale = data_config['scale']
    option = data_config['option']
    add_noise = data_config['add_noise']
    noise = data_config['noise']
    predict_res = data_config['predict_res']

    skip_training = False
    save_model = True

    print('-'*20 + ' Config ' + '-'*20, flush=True)
    print(model_config, flush=True)
    print(data_config, flush=True)
    print('-'*50, flush=True)

    model = Transformer(feature_size=feature_size,num_enc_layers=num_enc_layers,num_dec_layers = num_dec_layers,\
        d_ff = d_ff, dropout=dropout,num_head=num_head,pe_type=pe_type,grid_size=grid_size,mask_type=mask_type,patch_size=patch_size,window_size=window_size,decoder_only=decoder_only)


    device = "cpu"
    if torch.cuda.is_available():
        device = "cuda:0"
        if torch.cuda.device_count() > 1:
            model = nn.parallel.DistributedDataParallel(model)
    print('Using device: ',device)
    model.to(device)
      
    criterion = nn.MSELoss()
    optimizer = optim.AdamW(model.parameters(), lr=lr)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=1, gamma=lr_decay)
    #writer = tensorboard.SummaryWriter('/scratch/yd1008/tensorboard_output/')
    
    # if checkpoint_dir:
    #     checkpoint = os.path.join(checkpoint_dir, "checkpoint")
    #     model_state, optimizer_state = torch.load(checkpoint)
    #     model.load_state_dict(model_state)
    #     optimizer.load_state_dict(optimizer_state)
    
    ### SPECIFYING use_coords=True WILL RETURN DATALOADERS FOR COORDS
    train_loader, test_loader, scaler = get_data_loaders(train_proportion, test_proportion, val_proportion,\
        pred_size = 1, batch_size = batch_size, num_workers = 2, pin_memory = False, use_coords = True, use_time = True,\
        test_mode = True, scale = scale, window_size = window_size, grid_size = grid_size, patch_size = patch_size, \
        option = option, predict_res = predict_res, add_noise = add_noise, noise = noise, csv_path = csv_path)
    
    train_losses = []
    test_losses = []
    tolerance = 5
    best_test_loss = float('inf')
    Early_Stopping = early_stopping(patience=tolerance)
    counter_old = 0
    x1, x2, x3 = patch_size


    if os.path.exists(root_dir+'/best_model.pth') and skip_training:
        model.load_state_dict(torch.load(root_dir+'/best_model.pth'))
    else:
        for epoch in range(1, epochs + 1):    
            model.train() 
            total_loss = 0.
            start_time = time.time()

            for i, ((src, tgt), (src_coord, tgt_coord), (src_ts, tgt_ts)) in enumerate(train_loader):
                #print(f'i: {i}, src_coord: {src_coord}, tgt_coord: {tgt_coord}, src_ts: {src_ts}, tgt_ts: {tgt_ts}', flush=True)
                src, tgt, src_coord, tgt_coord, src_ts, tgt_ts = src.to(device), tgt.to(device), \
                                                            src_coord.to(device), tgt_coord.to(device), src_ts.to(device), tgt_ts.to(device)
                optimizer.zero_grad()
                output = model(src, tgt, src_coord, tgt_coord, src_ts, tgt_ts)
                # output, truth = process_one_batch(src, tgt, src_coord, tgt_coord, src_ts, tgt_ts, patch_size)
                loss = criterion(output[:,-x1*x2*x3:,:], tgt[:,-x1*x2*x3:,:])
                total_loss += loss.item()
                loss.backward()
                optimizer.step()

            avg_train_loss = total_loss*batch_size/len(train_loader.dataset)
            total_test_loss = evaluate(model, test_loader, criterion, patch_size=patch_size, predict_res = predict_res)
            avg_test_loss = total_test_loss/len(test_loader.dataset)

            
            train_losses.append(avg_train_loss)
            test_losses.append(avg_test_loss)
            

            if epoch==1: ###DEBUG
                print(f'Total of {len(train_loader.dataset)} samples in training set and {len(test_loader.dataset)} samples in test set', flush=True)

            print(f'Epoch: {epoch}, train_loss: {avg_train_loss}, test_loss: {avg_test_loss}, lr: {scheduler.get_last_lr()}, training time: {time.time()-start_time} s', flush=True)

            if (epoch%2 == 0):
                print(f'Saving prediction for epoch {epoch}', flush=True)
                predict_model(model, test_loader, epoch, config=best_config, \
                                    plot=True, plot_range=[0,0.01], final_prediction=False, predict_res = predict_res)   

            #writer.add_scalar('train_loss',avg_train_loss,epoch)
            #writer.add_scalar('test_loss',avg_test_loss,epoch)
            
            Early_Stopping(model, avg_test_loss)

            counter_new = Early_Stopping.counter
            if counter_new != counter_old:
                scheduler.step()  # update lr if early stop
                counter_old = counter_new
            if Early_Stopping.early_stop:
                break

        #save model
        if save_model:
            if os.path.exists(root_dir + '/best_model.pth'):  # checking if there is a file with this name
                os.remove(root_dir + '/best_model.pth')  # deleting the file
                torch.save(model.state_dict(), root_dir + '/best_model.pth')
            else:
                torch.save(model.state_dict(), root_dir + '/best_model.pth')
### Plot losses        
    xs = np.arange(len(train_losses))
    fig, ax = plt.subplots(nrows =1, ncols=1, figsize=(20,10))
    ax.plot(xs,train_losses)
    fig.savefig(root_dir + '/figs/loss' + f"/train_loss_pe{best_config['pe_type']}_batch{best_config['batch_size']}_window{best_config['window_size']}_patch{best_config['patch_size']}.png")
    plt.close(fig)
    fig, ax = plt.subplots(nrows =1, ncols=1, figsize=(20,10))
    ax.plot(xs,test_losses)
    fig.savefig(root_dir + '/figs/loss' + f"/test_loss_pe{best_config['pe_type']}_batch{best_config['batch_size']}_window{best_config['window_size']}_patch{best_config['patch_size']}.png")
    plt.close(fig)

### Predict
    start_time = time.time()
    final_result = predict_model(model, test_loader,  epoch, config=best_config ,\
                                            plot=True, plot_range=[0,1], final_prediction=True, predict_res = predict_res)
    prediction = final_result['prediction']
    print('-'*20 + ' Measure for Simulation Speed ' + '-'*20)
    print(f'Time to forcast {len(prediction)} samples: {time.time()-start_time} s' )

### Check MSE, MAE
    truth = final_result['truth']
    MSE = mean_squared_error(truth, prediction)
    MAE = mean_absolute_error(truth, prediction)
    R2 = r2_score(truth, prediction)
    EXPLAINED_VARIANCE_SCORE = explained_variance_score(truth, prediction)
    print('-'*20 + ' Measure for Simulation Performance ' + '-'*20)
    print(f'MSE: {MSE}, MAE: {MAE}, R2: {R2}, EXPLAINED_VARIANCE_SCORE: {EXPLAINED_VARIANCE_SCORE}')

### Save model result
    test_result_df = pd.DataFrame.from_dict(final_result)
    print('-'*20 + ' Dataframe for Final Result ' + '-'*20)
    print(test_result_df)
    test_result_df.to_csv(root_dir + '/transformer_prediction.csv')

### slice plot
    img_dir = root_dir + '/slice_plot' 
    pred_df = pd.read_csv(root_dir + '/transformer_prediction.csv',index_col=0)
    grid_size = [16,16,16]
    axis_colnames = ['x1','x2','x3']
    slice_axis_index = 0
    pred_colname = 'prediction'
    truth_colname = 'truth'
    time_colname = 'time'
    plot_forecast(pred_df=pred_df, grid_size=grid_size, axis_colnames=axis_colnames, slice_axis_index=2, \
                        pred_colname=pred_colname,truth_colname=truth_colname, time_colname=time_colname,  \
                        plot_anime = True, img_dir = img_dir, config=best_config) 

### plot value at specific positions against rollout timesteps
    pt_plot(root_dir=root_dir, final_result=final_result, nrows=3, ncols=3, grid_size = 16, pts_selection='movement')