#!/bin/bash python
import os
import numpy as np
import pandas as pd
import math
import torch 
import torch.nn as nn
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib import patches
from _arfima import arfima
from utils import *
from athena_read import *
from sklearn.preprocessing import StandardScaler
### VARIABLES(KEYS) IN DATASET
# dict_keys(['Coordinates', 'DatasetNames', 'MaxLevel', 'MeshBlockSize', 'NumCycles', \
# 'NumMeshBlocks', 'NumVariables', 'RootGridSize', 'RootGridX1', 'RootGridX2', 'RootGridX3', \
# 'Time', 'VariableNames', 'x1f', 'x1v', 'x2f', 'x2v', 'x3f', 'x3v', 'rho', 'press', 'vel1', 'vel2', 'vel3'])

def to_windowed(data, meshed_blocks, pred_size, window_size , patch_size=(1,1,16), option='patch', patch_stride = (1,1,1)):
    """
    window_size: Here represents the number of time steps in each window
    patch_size: (x1,x2,x3), determines the shape of the cuboid patch
    patch_stride: (s1,s2,s3), how many number of values patches move around in each meshblock in x,y,z direction
    """
    out = []
    if option == 'space':
        length = len(data) - window_size
        for i in range(length):
            feature = np.array(data[i:i+(window_size)])
            target = np.array(data[i+pred_size:i+window_size+pred_size])
            out.append((feature, target))
        patches_per_block = None 

    elif option == 'time':
        nx1, nx2, nx3 = meshed_blocks
        length = len(data)-nx1*nx2*nx3*window_size
        for i in range(length):
            feature  = np.array(data[[i+nx1*nx2*nx3*k for k in range(window_size)]])
            target = np.array(data[[i+nx1*nx2*nx3*(k+pred_size) for k in range(window_size)]])        
            out.append((feature,target))
        patches_per_block = None 

    elif option == 'patch':
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
                                for time in range(window_size-pred_size+1) for j in range(x1) for k in range(x2) for l in range(x3)]])
            target  = np.array(data[[i + (time+pred_size)*nx1*nx2*nx3 + j*(nx2*nx3) + k*(nx3) + l \
                                for time in range(window_size-pred_size+1) for j in range(x1) for k in range(x2) for l in range(x3)]])  
            out.append((feature,target))
        patches_per_block = np.prod([nx1//x1,nx2//x2,nx3//x3])
        
    elif option == 'patch_overlap':
        x1, x2, x3 = patch_size
        nx1, nx2, nx3 = meshed_blocks
        stride_x, stride_y, stride_z = patch_stride
        vertices = []
        for t in range(int((len(data)-nx1*nx2*nx3*window_size)/(nx1*nx2*nx3))):
            for k in range(math.floor((nx3-x3)/stride_z+1)):
                for j in range(math.floor((nx2-x2)/stride_y+1)):
                    for i in range(math.floor((nx1-x1)/stride_x+1)):
                        vertices.append(t*nx1*nx2*nx3 + k*nx1*nx2 + j*nx1 + i)
        for i in vertices:
            feature  = np.array(data[[i + time*nx1*nx2*nx3 + l*(nx2*nx3) + k*(nx3) + j \
                                for time in range(window_size) for j in range(x1) for k in range(x2) for l in range(x3)]])
            target  = np.array(data[[i + (time+pred_size)*nx1*nx2*nx3 + l*(nx2*nx3) + k*(nx3) + j \
                                for time in range(window_size) for j in range(x1) for k in range(x2) for l in range(x3)]])      
            out.append((feature,target))
        patches_per_block = np.prod([nx1-x1+1,nx2-x2+1,nx3-x3+1])
            
    return np.array(out), patches_per_block


def train_test_val_split(data, meshed_blocks, train_proportion = 0.6, val_proportion = 0.2, test_proportion = 0.2\
              , pred_size = 1, scale = False, window_size = 10, patch_size=(4,4,4), option='patch', \
              add_noise=True, noise=(0,1)):
      
    scaler = StandardScaler()
    if scale == True:
        data = scaler.fit_transform(data.reshape(-1, 1)).reshape(-1)
    if option in ['patch','patch_overlap']: ### Force each set start on a new block
        windows, patches_per_block = to_windowed(data, meshed_blocks, pred_size, window_size, patch_size, option)
        total_num_blocks = int(len(data)/np.prod(meshed_blocks)) #-(window_size-1)-(pred_size)
        window_adjust_length = (window_size-1)+pred_size ###Move the sliding window to cover the data lost on the edges

        train_num_blocks = int(total_num_blocks*train_proportion)-window_adjust_length
        val_num_blocks = int(total_num_blocks*val_proportion)

        val_start_block = train_num_blocks

        train_data_size = train_num_blocks*patches_per_block
        val_data_size = val_num_blocks*patches_per_block

        val_start_index = val_start_block*patches_per_block

        train = windows[:train_data_size]
        val = windows[val_start_index:val_start_index+val_data_size]
        test = windows[val_start_index+val_data_size:]
        # if option == 'patch_overlap': ###Retain the non-overlap test set in patch mode
        #     test = train_test_val_split(data, meshed_blocks, train_proportion, val_proportion, test_proportion, pred_size, scale, window_size, patch_size, option='patch')[2]
        #     test = test.numpy() ###Might not be efficient...
        # else: 
        #     test = windows[val_start_index+val_data_size:]
    else:
        windows = to_windowed(data, meshed_blocks, pred_size, window_size, patch_size, option)

        total_len = len(windows)
        train_len = int(total_len*train_proportion)
        val_len = int(total_len*val_proportion)
        
        train = windows[0:train_len]
        val = windows[train_len:(train_len+val_len)]
        test = windows[(train_len+val_len):]
    
    if add_noise == True:
        mu = noise[0]
        sigma = noise[1]
        train_noise = np.random.normal(mu, sigma, train.shape)
        train = train + train_noise
    
    print(train.shape,val.shape,test.shape)
    train_data = torch.from_numpy(train).float()
    val_data = torch.from_numpy(val).float()
    test_data = torch.from_numpy(test).float()
    
    return train_data,val_data,test_data,scaler
    


## Adjust __init__ to fit the inputs
class CustomDataset(torch.utils.data.Dataset):
    def __init__(self,x,coords,timestamp):
        self.x=x
        self.coords=coords
        self.timestamp=timestamp
 
    def __len__(self):
        return len(self.x)
 
    def __getitem__(self,idx):
        return((self.x[idx][0].view(-1,1), self.x[idx][1].view(-1,1)),(self.coords[idx][0], self.coords[idx][1]),(self.timestamp[idx][0].view(-1,1), self.timestamp[idx][1].view(-1,1)))
    

def get_data_loaders(train_proportion = 0.5, test_proportion = 0.25, val_proportion = 0.25, \
                        pred_size =1, batch_size = 16, num_workers = 1, pin_memory = True, \
                        use_coords = True, use_time = True, test_mode = False, scale = False, \
                        window_size = 10, grid_size = 16, patch_size=(4,4,4), option='patch', predict_res=False, \
                        add_noise=True, noise=(0,1e-2), csv_path = '/scratch/zh2095/nyu-capstone/data/data_original_16.csv'): 
    np.random.seed(505)
    
    df = pd.read_csv(csv_path)
    data = df['target'].to_numpy()
    coords = df[['x1','x2','x3']].to_numpy()
    timestamps = df['time'].to_numpy()
    meshed_blocks = (grid_size, grid_size, grid_size)

    ###FOR SIMPLE TEST SINE AND COSINE 
    #long_range_stationary_x_vals = (np.sin(2*np.pi*time_vec/period))+(np.cos(3*np.pi*time_vec/period)) + 0.25*np.random.randn(time_vec.size)
    ###FOR ARFIMA TEST
    #data = arfima([0.5,0.4],0.3,[0.2,0.1],10000,warmup=2^10)

    if use_coords:
        print('-'*20,'split for coords')
        train_coords,val_coords,test_coords, _ = train_test_val_split(\
            coords, meshed_blocks = meshed_blocks, train_proportion = train_proportion\
            , val_proportion = val_proportion, test_proportion = test_proportion\
            , pred_size = pred_size, scale = False, window_size = window_size, \
            patch_size = patch_size, option = option, add_noise=False, noise=(0,1e-2))
        print(f'train_coords: {train_coords.shape}')


    if use_time:
        print('-'*20,'split for timestamp')
        train_timestamps,val_timestamps,test_timestamps, _ = train_test_val_split(\
            timestamps, meshed_blocks = meshed_blocks, train_proportion = train_proportion\
            , val_proportion = val_proportion, test_proportion = test_proportion\
            , pred_size = pred_size, scale = False, window_size = window_size, \
             patch_size = patch_size, option = option, add_noise=False, noise=(0,1e-2))
        print(f'train_timestamps: {train_timestamps.shape}')

    print('-'*20,'split for data')
    train_data,val_data,test_data, scaler = train_test_val_split(\
        data, meshed_blocks = meshed_blocks, train_proportion = train_proportion\
        , val_proportion = val_proportion, test_proportion = test_proportion\
        , pred_size = pred_size, scale = scale, window_size = window_size, \
        patch_size = patch_size, option = option, add_noise=add_noise, noise=(0,1e-2))
    print(f'train_data: {train_data.shape}')

#----------------------------------------------------------------
### Save the original data table for reconstructing from residual predictions. May need to be optimized?
    if predict_res: 
        a = np.hstack([timestamps.reshape(-1,1), coords, data_original.reshape(-1,1)])
        a = a[np.argsort(a[:, 3])]
        a = a[np.argsort(a[:, 2], kind='stable')]
        a = a[np.argsort(a[:, 1], kind='stable')]
        a = a[np.argsort(a[:, 0], kind='stable')]
        if scale==True:
            data_origin_dict = {'time': a[:,0], 'x1': a[:,1], 'x2': a[:,2], 'x3': a[:,3], 'truth_original':scaler.inverse_transform(a[:,4])}
        elif scale==False:
            data_origin_dict = {'time': a[:,0], 'x1': a[:,1], 'x2': a[:,2], 'x3': a[:,3], 'truth_original':a[:,4]}
        data_origin_df = pd.DataFrame.from_dict(data_origin_dict)
        data_origin_df.to_csv('/scratch/zh2095/nyu-capstone/yd_test/tune_results/' + '/data_original.csv')
        #print(data_origin_df,flush=True)
 #----------------------------------------------------------------   

    if test_mode:
        val_test_data = torch.cat((val_data, test_data),0)
        val_test_coords = torch.cat((val_coords,test_coords),0)
        val_test_timestamps = torch.cat((val_timestamps,test_timestamps),0)

        ### Get the first block in test_original to perform rollout that gives back the original data based on predicted residuals

        dataset_train, dataset_test = CustomDataset(train_data,train_coords,train_timestamps), CustomDataset(val_test_data,val_test_coords,val_test_timestamps)
        train_loader = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size, \
                                        drop_last=False, num_workers=num_workers, pin_memory=pin_memory,\
                                        persistent_workers=True, prefetch_factor = 16)
        test_loader = torch.utils.data.DataLoader(dataset_test, batch_size=batch_size, \
                                        drop_last=False, num_workers=num_workers, pin_memory=pin_memory,\
                                        persistent_workers=True, prefetch_factor = 128) 
        return train_loader, test_loader, scaler
    if not test_mode:                           
        dataset_train, dataset_test, dataset_val = CustomDataset(train_data,train_coords,train_timestamps), CustomDataset(test_data,test_coords,test_timestamps), CustomDataset(val_data,val_coords,val_timestamps)

        train_loader = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size, \
                                            drop_last=False, num_workers=num_workers, pin_memory=pin_memory,\
                                            persistent_workers=True, prefetch_factor = 16)
        test_loader = torch.utils.data.DataLoader(dataset_test, batch_size=batch_size, \
                                            drop_last=False, num_workers=num_workers, pin_memory=pin_memory,\
                                            persistent_workers=True, prefetch_factor = 16)
        val_loader = torch.utils.data.DataLoader(dataset_val, batch_size=batch_size, \
                                            drop_last=False, num_workers=num_workers, pin_memory=pin_memory,\
                                            persistent_workers=True, prefetch_factor = 16)
       
        return train_loader,val_loader, test_loader

# img_dir = 'figs' ###dir to save images to
# pred_df = pd.read_csv('transformer_prediction_coords.csv',index_col=0) ###dir of csv file, or pandas dataframe


# grid_size = [16,16,16]
# axis_colnames = ['x1','x2','x3']
# slice_axis_index = 0
# pred_colname = 'prediction'
# truth_colname = 'truth'
# time_colname = 'time'


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
    if type(grid_size)==int:
        grid_size = [grid_size]*3
    if type(pred_df)== str:
        preds_all = pd.read_csv(pred_df,index_col=None)
    else:
        preds_all = pred_df

    v_max, v_min = max(preds_all[truth_colname].values),min(preds_all[truth_colname].values)
    v_max_res, v_min_res = max(preds_all[truth_colname].values-preds_all[pred_colname].values),min(preds_all[truth_colname].values-preds_all[pred_colname].values)

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
        if single_simulation_df.shape[0]>=predictions_per_simulation:
            if single_simulation_df.shape[0]>predictions_per_simulation:
                single_simulation_df = single_simulation_df.groupby([time_colname]+axis_colnames).mean().reset_index()
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
                im_pred = axes[slice_axis_shape-i-1][0].imshow(preds[i],vmin=v_min, vmax=v_max, aspect='equal',animated=False)
                axes[slice_axis_shape-i-1][0].set_ylabel(f'Slice {i}',size=15)
                im_truth = axes[slice_axis_shape-i-1][1].imshow(truth[i],vmin=v_min, vmax=v_max, aspect='equal',animated=False)
                im_residual = axes[slice_axis_shape-i-1][2].imshow(truth[i]-preds[i],vmin=v_min_res, vmax=v_max_res,aspect='equal',animated=False)
                
                fig.colorbar(im_truth,ax=axes[slice_axis_shape-i-1][1])
                fig.colorbar(im_pred,ax=axes[slice_axis_shape-i-1][0])
                fig.colorbar(im_residual,ax=axes[slice_axis_shape-i-1][2])
            else:
                im_pred = axes[slice_axis_shape-i-1][0].imshow(preds[i],vmin=v_min, vmax=v_max, aspect='equal',animated=True)
                axes[slice_axis_shape-i-1][0].set_ylabel(f'Slice {i}',size=15)
                im_truth = axes[slice_axis_shape-i-1][1].imshow(truth[i],vmin=v_min, vmax=v_max, aspect='equal',animated=True)
                im_residual = axes[slice_axis_shape-i-1][2].imshow(truth[i]-preds[i],vmin=v_min_res, vmax=v_max_res, aspect='equal',animated=True)
                
                fig.colorbar(im_truth,ax=axes[slice_axis_shape-i-1][1])
                fig.colorbar(im_pred,ax=axes[slice_axis_shape-i-1][0])
                fig.colorbar(im_residual,ax=axes[slice_axis_shape-i-1][2])

        axes[-1,0].annotate('Forecast',(0.5, 0), xytext=(0, -30),textcoords='offset points', xycoords='axes fraction', ha='center', va='top', size=20)
        axes[-1,1].annotate('Truth',(0.5, 0), xytext=(0, -30),textcoords='offset points', xycoords='axes fraction', ha='center', va='top', size=20)
        axes[-1,2].annotate('Residual',(0.5, 0), xytext=(0, -30),textcoords='offset points', xycoords='axes fraction', ha='center', va='top', size=20)
        #axes[-1,0].annotate('Slice number', (0, 0.5), xytext=(-50, 0), textcoords='offset points', xycoords='axes fraction', ha='left', va='center', size=15, rotation=90)
        fig.suptitle(f'Forecasts on slices across {slice_axis_colname} at timestamp {ts}',x=0.2,y=1,size=20)
        plt.savefig(img_dir+f'/ts_{ts}_result.png', bbox_inches="tight")
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
                    im_pred = axes[slice_axis_shape-i-1][0].imshow(preds[i],vmin=v_min, vmax=v_max, aspect='equal',animated=False)
                    axes[slice_axis_shape-i-1][0].set_ylabel(f'Slice {i}',size=15)
                    im_truth = axes[slice_axis_shape-i-1][1].imshow(truth[i],vmin=v_min, vmax=v_max, aspect='equal',animated=False)
                    im_residual = axes[slice_axis_shape-i-1][2].imshow(truth[i]-preds[i],vmin=v_min_res, vmax=v_max_res, aspect='equal',animated=False)
                else:
                    im_pred = axes[slice_axis_shape-i-1][0].imshow(preds[i],vmin=v_min, vmax=v_max, aspect='equal',animated=True)
                    axes[slice_axis_shape-i-1][0].set_ylabel(f'Slice {i}',size=15)
                    im_truth = axes[slice_axis_shape-i-1][1].imshow(truth[i],vmin=v_min, vmax=v_max, aspect='equal',animated=True)
                    im_residual = axes[slice_axis_shape-i-1][2].imshow(truth[i]-preds[i],vmin=v_min_res, vmax=v_max_res, aspect='equal',animated=True)
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

def plot_demo(num_timestamps, grid_size, patch_size, img_dir):
    '''
    Parameters:
        num_timestamps: int, number of simulations to draw
        grid_size: int or list-like, dimensions of one meshblock
        patch_size: list-like, dimensions of patches
        img_dir: str, path to folder where plots are saved
    '''
    if type(grid_size)==int:
        grid_size = [grid_size]*3
    def explode(data):
        size = np.array(data.shape)*2
        data_e = np.zeros(size - 1, dtype=data.dtype)
        data_e[::2, ::2, ::2] = data
        return data_e

    def create_indices(grid_size,patch_size):
        n_voxels = np.zeros((grid_size[0], grid_size[1], grid_size[2]), dtype=bool)
        n_voxels[-patch_size[0]:, :patch_size[1], -patch_size[2]:] = True
        # n_voxels[-1, 0, :] = True
        # n_voxels[1, 0, 2] = True
        # n_voxels[2, 0, 1] = True
        facecolors = np.where(n_voxels, '#FFD65DC0', '#7A88CCC0')
        edgecolors = np.where(n_voxels, '#BFAB6E', '#7D84A6')
        filled = np.ones(n_voxels.shape)

        filled_2 = explode(filled)
        fcolors_2 = explode(facecolors)
        ecolors_2 = explode(edgecolors)

        x, y, z = np.indices(np.array(filled_2.shape) + 1).astype(float) // 2
        x[0::2, :, :] += 0.05
        y[:, 0::2, :] += 0.05
        z[:, :, 0::2] += 0.05
        x[1::2, :, :] += 0.95
        y[:, 1::2, :] += 0.95
        z[:, :, 1::2] += 0.95
        return x,y,z,filled_2,fcolors_2,ecolors_2

    blocks_per_patch = np.prod(patch_size)
    x_fullgrid, y_fullgrid, z_fullgrid,filled_fullgrid,fcolors_fullgrid,ecolors_fullgrid = create_indices(grid_size,patch_size)
    x_flattened, y_flattened, z_flattened,filled_flattened,fcolors_flattened,ecolors_flattened = create_indices((blocks_per_patch,1,1),(blocks_per_patch,1,1))
    fig = plt.figure(figsize=(3*num_timestamps,6))
    transFigure = fig.transFigure.inverted()
    for ts in range(num_timestamps):
        ax1 = fig.add_subplot(2, num_timestamps, ts+1, projection='3d')
        ax1.voxels(x_fullgrid, y_fullgrid, z_fullgrid, filled_fullgrid, facecolors=fcolors_fullgrid, edgecolors=ecolors_fullgrid)
        ax1.set_axis_off()
        ax1.set_title(f'Simulation @ t={ts+1}')
        
        ax2 = fig.add_subplot(2, num_timestamps, num_timestamps+ts+1, projection='3d')
        ax2.voxels(x_flattened, y_flattened, z_flattened, filled_flattened, facecolors=fcolors_flattened, edgecolors=ecolors_flattened)
        ax2.set_axis_off()
        ax2.set_ylim(1-blocks_per_patch,1)
        ax2.set_zlim(1-blocks_per_patch,1)
        ax2.annotate('Flatten', xy=(0, 0), xytext=(-0.05, 0.12),fontsize=11)
        if ts!=num_timestamps-1:
            ax2.annotate('+', xy=(0, 0), xytext=(0.11, 0.06),fontsize=15)
        
        xyA = [0.01,-0.02]
        xyB = [0.02,0.065]
        coord1 = transFigure.transform(ax1.transData.transform(xyA))
        coord2 = transFigure.transform(ax2.transData.transform(xyB))
        arrow = patches.FancyArrowPatch(coord1,coord2,shrinkA=0,shrinkB=0,transform=fig.transFigure,color='Black',\
                                        arrowstyle="-|>",mutation_scale=30,linewidth=1.5,)
        fig.patches.append(arrow)

    #plt.show()
    plt.savefig(img_dir+'patch_demo.png', bbox_inches="tight", facecolor='white')



def pt_plot(root_dir, final_result, nrows=3, ncols=3, grid_size = 16, pts_selection='movement'):
    prediction = final_result['prediction']
    truth = final_result['truth']
    time = final_result['time']
    num_timesteps = len(np.unique(time))
    # number of points you want to plootted
    num_pts = int(nrows*ncols)

    if pts_selection == 'movement':  # points with the most total flucuation
        lst = [truth[t*grid_size**3:(t+1)*grid_size**3] for t in range(num_timesteps)]
        total_movement = 0
        for t in range(num_timesteps-1):
            total_movement += abs(lst[t+1]-lst[t]) 
        movement_sort = total_movement.argsort()
        idx = movement_sort[-num_pts:]

    elif pts_selection == 'min':  # points with the min value at the initial state
        initial = truth[:grid_size**3]
        idx = initial.argsort()[:num_pts]

    elif pts_selection == 'max':  # points with the max value at the initial state
        initial = truth[:grid_size**3]
        idx = initial.argsort()[-num_pts:]
    
    elif pts_selection == 'random':  # randomly selected points
        idx = np.random.choice(grid_size**3, size=num_pts, replace=False)

    fig, ax = plt.subplots(nrows=nrows, ncols=ncols, figsize=(20,12))
    plt.suptitle(f'rho vs rollout timesteps at points selected by {pts_selection}', fontsize=20)
    for i in range(nrows):
        for j in range(ncols):
            pt_truth = np.array([truth[idx[i*j+j] + t*grid_size**3] for t in range(num_timesteps)])
            pt_pred = np.array([prediction[idx[i*j+j] + t*grid_size**3] for t in range(num_timesteps)])

            ax[i,j].plot(pt_truth, label = 'truth', ls='-')
            ax[i,j].plot(pt_pred, label = 'pred', ls='-')
            ax[i,j].plot(pt_pred - pt_truth, label = 'residual', ls='-.')
            ax[i,j].set_ylabel('turbulence density')
            ax[i,j].set_xlabel('rollout timesteps')
            ax[i,j].axhline(y=0)
            ax[i,j].legend()
    
    fig.savefig(root_dir + '/figs/final_plot' + f"/points_{pts_selection}")