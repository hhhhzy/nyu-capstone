#!/bin/bash python
import os
import numpy as np
import pandas as pd
import torch 
import torch.nn as nn
from athena_read import *
from sklearn.preprocessing import StandardScaler
from matplotlib import animation
import matplotlib.pyplot as plt

def get_rho(data_path):
    lst = sorted(os.listdir(data_path))[4:-1]
    rho = []
    coords = []
    timestamps = []
    for name in lst:
        path = data_path+'/'+name
        d = athdf(path)
        nx1 = len(d['x1v'])
        nx2 = len(d['x2v'])
        nx3 = len(d['x3v'])
        coord = np.transpose(np.array(np.meshgrid(np.arange(nx1),np.arange(nx2),np.arange(nx3))), axes=[2,1,3,0]).reshape(-1,3)
        rho.append(d['rho'])
        timestamp_repeated = [d['Time']]*(np.prod(d['rho'].shape))
        timestamps.extend(timestamp_repeated) ### Add nx1*nx2*nx3 time values into the output list
        #print('rho:',d['rho'].shape, 'coord.shape:',coord.shape,'len timestamp:',len(timestamp_repeated))
        coords.extend(coord)

    rho = np.array(rho)
    meshed_blocks = (nx1, nx2, nx3)
    timestamps = np.array(timestamps)
    uniq, index = np.unique(timestamps, return_index=True)
    uniq[index.argsort()]
    rho_reshaped = rho.flatten()
    coords = np.array(coords)
    #print(f'rho shape: {rho_reshaped.shape}, coords shape: {coords.shape}')
    return rho_reshaped, meshed_blocks, coords, timestamps



def to_windowed(data, meshed_blocks, pred_size, window_size=10, patch_size=(1,1,16)):
    """
    window_size: Here represents the number of time steps in each window
    patch_size: (x1,x2,x3), determines the shape of the cuboid patch
    """
    out = []
    x1, x2, x3 = patch_size
    nx1, nx2, nx3 = meshed_blocks

    vertices = []
    for t in range(int((len(data)-nx1*nx2*nx3*window_size)/(nx1*nx2*nx3))):
        for i in range(nx1//x1):
            for j in range(nx2//x2):
                for k in range(nx3//x3):
                    vertices.append(t*nx1*nx2*nx3 + i*x1*nx2*nx3 + j*x2*nx3 + k*x3)

    for i in vertices:
        feature  = np.array(data[[i + time*nx1*nx2*nx3 + j*(nx2*nx3) + k*(nx3) + l \
                                for time in range(window_size) for j in range(x1) for k in range(x2) for l in range(x3)]])
        target  = np.array(data[[i + (time+pred_size)*nx1*nx2*nx3 + j*(nx2*nx3) + k*(nx3) + l \
                                for time in range(window_size) for j in range(x1) for k in range(x2) for l in range(x3)]])      
        out.append((feature,target))
            
    return np.array(out)


def train_test_val_split(data, meshed_blocks, train_proportion = 0.6, val_proportion = 0.2, test_proportion = 0.2\
              ,  pred_size = 1, scale = False, window_size=10, patch_size = (1,1,16)):

    scaler = StandardScaler()
    if scale == True:
        data = scaler.fit_transform(data.reshape(-1, 1)).reshape(-1)
    
    x_vals = to_windowed(data, meshed_blocks, pred_size, window_size, patch_size)

    total_len = len(x_vals)
    train_len = int(total_len*train_proportion)
    val_len = int(total_len*val_proportion)
    
    train = x_vals[0:train_len]
    val = x_vals[train_len:(train_len+val_len)]
    test = x_vals[(train_len+val_len):]

    train_data = torch.from_numpy(train).float()
    val_data = torch.from_numpy(val).float()
    test_data = torch.from_numpy(test).float()

    return train_data,val_data,test_data,scaler


### Adjust __init__ to fit the inputs
class CustomDataset(torch.utils.data.Dataset):
    def __init__(self,x,coords,timestamp):
        self.x=x
        self.coords=coords
        self.timestamp=timestamp
 
    def __len__(self):
        return len(self.x)
 
    def __getitem__(self,idx):
        return((self.x[idx][0].view(-1,1), self.x[idx][1].view(-1,1)),(self.coords[idx][0], self.coords[idx][1]),(self.timestamp[idx][0].view(-1,1), self.timestamp[idx][1].view(-1,1)))
    

def get_data_loaders(train_proportion = 0.5, test_proportion = 0.25, val_proportion = 0.25,\
                        pred_size =1, batch_size = 16, num_workers = 1, pin_memory = True, \
                        use_coords = True, use_time = True, test_mode = False, scale = False, \
                        window_size = 10, patch_size = (1,1,16)): 

    #device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    np.random.seed(505)
    
    #data_path='/scratch/tl2204/data/data_turb_dedt1_16_seed9'
    data_path='/scratch/tl2204/data/data_turb_dedt1_16_seed8'
    #data_path='C:/Users/52673/Desktop/NYU MSDS/3-DS-1006 CAPSTONE/data_turb_dedt1_16'
    data, meshed_blocks, coords, timestamps = get_rho(data_path)

    ###FOR SIMPLE TEST SINE AND COSINE 
    #long_range_stationary_x_vals = (np.sin(2*np.pi*time_vec/period))+(np.cos(3*np.pi*time_vec/period)) + 0.25*np.random.randn(time_vec.size)
    ###FOR ARFIMA TEST
    #data = arfima([0.5,0.4],0.3,[0.2,0.1],10000,warmup=2^10)

    if use_coords:
        print('-'*20,'split for coords')
        train_coords,val_coords,test_coords, scaler = train_test_val_split(\
            coords, meshed_blocks = meshed_blocks, train_proportion = train_proportion\
            , val_proportion = val_proportion, test_proportion = test_proportion\
            , pred_size = pred_size, scale = False, window_size = window_size, patch_size = patch_size)
        print(f'train_coords: {train_coords.shape}')

    if use_time:
        print('-'*20,'split for timestamp')
        train_timestamps,val_timestamps,test_timestamps, scaler = train_test_val_split(\
            timestamps, meshed_blocks = meshed_blocks, train_proportion = train_proportion\
            , val_proportion = val_proportion, test_proportion = test_proportion\
            , pred_size = pred_size, scale = False, window_size = window_size, patch_size = patch_size)
        print(f'train_timestamps: {train_timestamps.shape}')

    print('-'*20,'split for data')
    train_data,val_data,test_data, scaler = train_test_val_split(\
        data, meshed_blocks = meshed_blocks, train_proportion = train_proportion\
        , val_proportion = val_proportion, test_proportion = test_proportion\
        , pred_size = pred_size, scale = scale, window_size = window_size, patch_size = patch_size)
    ## add noise (experiment)
    # train_data += torch.empty(list(train_data.size())).normal_(0.,0.5)
    print(f'train_data: {train_data.shape}')
    
    if test_mode:
        train_val_data = torch.cat((train_data,val_data),0)
        ## BEGIN add noise
        #train_val_data += torch.empty(list(train_val_data.size())).normal_(0.,1.5)
        ## END
        train_val_coords = torch.cat((train_coords,val_coords),0)
        train_val_timestamps = torch.cat((train_timestamps,val_timestamps),0)

        dataset_train_val, dataset_test = CustomDataset(train_val_data,train_val_coords,train_val_timestamps), CustomDataset(test_data,test_coords,test_timestamps)
    
        train_val_loader = torch.utils.data.DataLoader(dataset_train_val, batch_size=batch_size, \
                                        drop_last=False, num_workers=num_workers, pin_memory=pin_memory,\
                                        persistent_workers=True, prefetch_factor = 16)
        test_loader = torch.utils.data.DataLoader(dataset_test, batch_size=1, \
                                        drop_last=False, num_workers=num_workers, pin_memory=pin_memory,\
                                        persistent_workers=True, prefetch_factor = 128) 

        # train_val_data_noisy = torch.empty(list(train_val_data.size())).normal_(0.,0.5)
        # dataset_train_val_noisy = CustomDataset(train_val_data_noisy,train_val_coords,train_val_timestamps)
        # train_val_loader_noisy =  torch.utils.data.DataLoader(dataset_train_val_noisy, batch_size=batch_size, \
        #                                 drop_last=False, num_workers=num_workers, pin_memory=pin_memory,\
        #                                 persistent_workers=True, prefetch_factor = 16)                              
        

        return train_val_loader, test_loader, scaler
    
    if not test_mode:

        #train_data += torch.empty(list(train_data.size())).normal_(0., 1.5)         

        dataset_train, dataset_test, dataset_val = CustomDataset(train_data,train_coords,train_timestamps), CustomDataset(test_data,test_coords,test_timestamps), CustomDataset(val_data,val_coords,val_timestamps)

        train_loader = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size, \
                                            drop_last=True, num_workers=num_workers, pin_memory=pin_memory,\
                                            persistent_workers=True, prefetch_factor = 16)
        test_loader = torch.utils.data.DataLoader(dataset_test, batch_size=batch_size, \
                                            drop_last=True, num_workers=num_workers, pin_memory=pin_memory,\
                                            persistent_workers=True, prefetch_factor = 16)
        val_loader = torch.utils.data.DataLoader(dataset_val, batch_size=batch_size, \
                                            drop_last=True, num_workers=num_workers, pin_memory=pin_memory,\
                                            persistent_workers=True, prefetch_factor = 16)

        # train_data_noisy = train_data + torch.empty(list(train_data.size())).normal_(0.,0.5)
        # dataset_train_noisy = CustomDataset(train_data_noisy,train_coords,train_timestamps)
        # train_loader_noisy = torch.utils.data.DataLoader(dataset_train_noisy, batch_size=batch_size, \
        #                                     drop_last=True, num_workers=num_workers, pin_memory=pin_memory,\
        #                                     persistent_workers=True, prefetch_factor = 16)
        
        return train_loader,val_loader, test_loader


def plot_forecast(pred_df=None, grid_size=16, axis_colnames=['x1','x2','x3'], slice_axis_index=0, \
                  pred_colname='prediction',truth_colname='truth', time_colname='time',  \
                  plot_anime = True, img_dir = 'figs', config={}):
    '''
    Notes: 
        please create two subfolders 'gif' and 'mp4' to save the animated slice plot for each trail 
    Parameters:
        pred_df: string of dir of csv file or pandas.Dataframe, predictions with coordinates and time
        grid_size: int or list-like, dimensions of one meshblock
        axis_colnames: list of strings, column names of coordinates in pred_df
        slice_axis_index: int, index of axis in axis_colnames to slice on 
        pred_colname: string, column name of predictions in pred_df
        truth_colname: string, column name of truths in pred_df
        time_colname: string, column name of timestamps in pred_df
        plot_anime: bool, animated plots will be saved if True 
        img_dir: str, path to folder where plots are saved 
        config: dictionary, the config of this plot, used for saving distinguishable animated plots for each trail
    Sample use:
        img_dir = 'figs' 
        pred_df = pd.read_csv('transformer_prediction_coords.csv',index_col=0) or 'transformer_prediction_coords.csv'
        grid_size = [16,16,16]
        axis_colnames = ['x1','x2','x3']
        slice_axis_index = 0
        pred_colname = 'prediction'
        truth_colname = 'truth'
        time_colname = 'time'
        plot_forecast(pred_df=pred_df, grid_size=grid_size, axis_colnames=axis_colnames, slice_axis_index=2, \
                        pred_colname=pred_colname,truth_colname=truth_colname, time_colname=time_colname,  \
                        plot_anime = True, img_dir = 'figs/', config=best_config)   
    '''
    if len(grid_size)!=3:
        grid_size = [grid_size]*3
    if type(pred_df)== str:
        preds_all = pd.read_csv(pred_df,index_col=None)
    else:
        preds_all = pred_df
        
    predictions_per_simulation = np.prod(grid_size)
    slice_axis_colname = axis_colnames[slice_axis_index]
    #nonslice_axis_colname = axis_colnames.remove(slice_axis_colname)
    slice_axis_shape = grid_size.pop(slice_axis_index)
    nonslice_axis_shape = grid_size
    timestamps = sorted(preds_all[time_colname].unique())
    axis_vals = sorted(preds_all[slice_axis_colname].unique())

    ### create a dict to save all values
    result_dict = {}
    print('Processing dataframe...')
    for timestamp in timestamps:
        single_simulation_df = preds_all.loc[(preds_all[time_colname]==timestamp)]
        if single_simulation_df.shape[0]==predictions_per_simulation:
            result_dict[timestamp] = {}
            result_dict[timestamp]['slice_axis_val'] = []
            result_dict[timestamp]['preds'] = []
            result_dict[timestamp]['truth'] = []
            for axis_val in axis_vals:
                slice_df = single_simulation_df.loc[single_simulation_df[slice_axis_colname]==axis_val]
                slice_preds = slice_df[pred_colname].values.reshape(nonslice_axis_shape)
                slice_truth = slice_df[truth_colname].values.reshape(nonslice_axis_shape)
                result_dict[timestamp]['slice_axis_val'].append(axis_val)
                result_dict[timestamp]['preds'].append(slice_preds)
                result_dict[timestamp]['truth'].append(slice_truth)    
        else:
            print(f'Found {single_simulation_df.shape[0]} predictions in simulation at timestamp {timestamp}, but expect {predictions_per_simulation}')

    print('Generating plots...')
    ### plot for each timestamp        
    for ts_idx,ts in enumerate(list(result_dict.keys())):
        fig,axes = plt.subplots(nrows = slice_axis_shape, ncols = 3, figsize=(40, 40),subplot_kw={'xticks': [], 'yticks': []})
        #plt.setp(axes, ylim=(0, 14),xlim=(0,2))
        plt.subplots_adjust(left=0.1,bottom=0, right=0.3, top=0.98, wspace=0, hspace=0.3)
        axis_val = result_dict[ts]['slice_axis_val']
        preds = result_dict[ts]['preds']
        truth = result_dict[ts]['truth']
        for i in range(slice_axis_shape):
            if ts_idx==0:
                axes[slice_axis_shape-i-1][0].imshow(preds[i],aspect='equal',animated=False)
                #fig.colorbar(im_pred,ax=axes[slice_axis_shape-i-1][0])
                axes[slice_axis_shape-i-1][0].set_ylabel(f'Slice {i}',size=15)
                axes[slice_axis_shape-i-1][1].imshow(truth[i],aspect='equal',animated=False)
                #fig.colorbar(im_truth,ax=axes[slice_axis_shape-i-1][1])
                axes[slice_axis_shape-i-1][2].imshow(truth[i]-preds[i],aspect='equal',animated=False)
                #fig.colorbar(im_residual,ax=axes[slice_axis_shape-i-1][2])
            else:
                axes[slice_axis_shape-i-1][0].imshow(preds[i],aspect='equal',animated=True)
                #fig.colorbar(im_pred,ax=axes[slice_axis_shape-i-1][0])
                axes[slice_axis_shape-i-1][0].set_ylabel(f'Slice {i}',size=15)
                axes[slice_axis_shape-i-1][1].imshow(truth[i],aspect='equal',animated=True)
                #fig.colorbar(im_truth,ax=axes[slice_axis_shape-i-1][1])
                axes[slice_axis_shape-i-1][2].imshow(truth[i]-preds[i],aspect='equal',animated=True)
                #fig.colorbar(im_residual,ax=axes[slice_axis_shape-i-1][2])

        axes[-1,0].annotate('Forecast',(0.5, 0), xytext=(0, -30),textcoords='offset points', xycoords='axes fraction', ha='center', va='top', size=20)
        axes[-1,1].annotate('Truth',(0.5, 0), xytext=(0, -30),textcoords='offset points', xycoords='axes fraction', ha='center', va='top', size=20)
        axes[-1,2].annotate('Residual',(0.5, 0), xytext=(0, -30),textcoords='offset points', xycoords='axes fraction', ha='center', va='top', size=20)
        #axes[-1,0].annotate('Slice number', (0, 0.5), xytext=(-50, 0), textcoords='offset points', xycoords='axes fraction', ha='left', va='center', size=15, rotation=90)
        fig.suptitle(f'Forecasts on slices across {slice_axis_colname} at timestamp {ts}',x=0.2,y=1,size=20)
        plt.savefig(img_dir + '/tmp_plot' + f'/ts_{ts}_result.png', bbox_inches="tight")
        plt.close()
        
    if plot_anime:
        imgs = []
        fig,axes = plt.subplots(nrows = slice_axis_shape, ncols = 3, figsize=(40, 40),subplot_kw={'xticks': [], 'yticks': []})
        plt.subplots_adjust(left=0.1,bottom=0, right=0.3, top=0.98, wspace=0, hspace=0.3)
        print('Generating animation...')
        for ts_idx,ts in enumerate(list(result_dict.keys())):
            axis_val = result_dict[ts]['slice_axis_val']
            preds = result_dict[ts]['preds']
            truth = result_dict[ts]['truth']
            tmp_imgs = []
            for i in range(slice_axis_shape):
                if ts_idx==0:
                    im_pred = axes[slice_axis_shape-i-1][0].imshow(preds[i],aspect='equal',animated=False)
                    axes[slice_axis_shape-i-1][0].set_ylabel(f'Slice {i}',size=15)
                    im_truth = axes[slice_axis_shape-i-1][1].imshow(truth[i],aspect='equal',animated=False)
                    im_residual = axes[slice_axis_shape-i-1][2].imshow(truth[i]-preds[i],aspect='equal',animated=False)
                else:
                    im_pred = axes[slice_axis_shape-i-1][0].imshow(preds[i],aspect='equal',animated=True)
                    axes[slice_axis_shape-i-1][0].set_ylabel(f'Slice {i}',size=15)
                    im_truth = axes[slice_axis_shape-i-1][1].imshow(truth[i],aspect='equal',animated=True)
                    im_residual = axes[slice_axis_shape-i-1][2].imshow(truth[i]-preds[i],aspect='equal',animated=True)
                    tmp_imgs.extend([im_pred,im_truth,im_residual])
            imgs.append(tmp_imgs)
        axes[-1,0].annotate('Forecast',(0.5, 0), xytext=(0, -30),textcoords='offset points', xycoords='axes fraction', ha='center', va='top', size=20)
        axes[-1,1].annotate('Truth',(0.5, 0), xytext=(0, -30),textcoords='offset points', xycoords='axes fraction', ha='center', va='top', size=20)
        axes[-1,2].annotate('Residual',(0.5, 0), xytext=(0, -30),textcoords='offset points', xycoords='axes fraction', ha='center', va='top', size=20)
        fig.suptitle(f'Forecasts on slices across {slice_axis_colname} animated',x=0.2,y=1,size=20)
        ani = animation.ArtistAnimation(fig, imgs, interval=500, repeat_delay = 1000, blit=True)
        try:
            writer = animation.FFMpegWriter(fps=30, bitrate=1800)
            ani.save(img_dir+"/mp4"+f"/{slice_axis_colname}_pe{config['pe_type']}_batch{config['batch_size']}_window{config['window_size']}_patch{config['patch_size']}.mp4", writer=writer) 
        except:
            print('Saving animation in .mp4 format, try installing ffmpeg package. \n Saving to .gif instead')
            ani.save(img_dir+"/gif"+f"/{slice_axis_colname}_pe{config['pe_type']}_batch{config['batch_size']}_window{config['window_size']}_patch{config['patch_size']}.gif")