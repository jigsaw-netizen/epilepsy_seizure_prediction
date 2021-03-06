# -*- coding: utf-8 -*-
"""
Created on Fri Feb 12 15:20:32 2021

@author: gijsb
"""

#%% Imports

from tqdm import tqdm
import sklearn.preprocessing as preprocessing
import numpy as np
import pandas as pd
from scipy.integrate import simps
import scipy.io as sio
import scipy.stats
import scipy.signal
from os import listdir
from os.path import isfile, join
from datetime import datetime

from utils import load_mat, zero_crossings, svd_entropy, total_energy, add_feature, band_energy, highres_total_energy

import warnings
warnings.filterwarnings('ignore')
import logging

#%% Parameters

DATA_PATH = 'C:/Users/gijsb/OneDrive/Documents/epilepsy_neurovista_data/'
TRAIN_PATHS = [f'Pat{i}Train' for i in [1, 2, 3]]
TEST_PATHS = [f'Pat{i}Test' for i in [1, 2, 3]]
FEATURE_SAVE_PATH = DATA_PATH # Path where output feature arrays will be saved

SAMPLING_FREQUENCY = 400
DOWNSAMPLING_RATIO = 5
CHANNELS = range(0,16)
BANDS = [0.1,1,4,8,12,30,70]
HIGHRES_BANDS = [0.1,1,4,8,12,30,70,180]


#%% logging

today_string = str(datetime.now())[0:19].replace('-', '_').replace(':', '_').replace(' ', '_')
log_filename = f'feature_generation_log_{today_string}.log'
logging.basicConfig(level=logging.DEBUG, 
                    filename=log_filename, 
                    format='%(asctime)s.%(msecs)03d %(levelname)s {%(module)s} [%(funcName)s] %(message)s', 
                    datefmt='%Y-%m-%d,%H:%M:%S')


#%% Feature generation loop

    
def generate_features(patient_number, data_path, is_training_data, save_to_disk = True):
    
    filenames = [f for f in listdir(data_path) if isfile(join(data_path, f))]
    filelist = [join(data_path, f) for f in listdir(data_path) if isfile(join(data_path, f))]


    logging.debug(f'generated filelist of length {len(filelist)} for patient {patient_number}; is_training_data = {is_training_data}')
    
    counter = 0
    for filename in tqdm(filenames):
        
        # Lists that will contain feature names and values, we will stack these to make X_train
        index = []
        features = []

        #Load file & normalise
        data = load_mat(join(data_path, filename))
        data = preprocessing.scale(data, axis=1, with_std=True)
        data_downsampled = scipy.signal.decimate(data, 5, zero_phase=True)
        
        logging.debug(f'starting feature generation file:{counter}')
        
        # ID features
        index.append('Patient')
        features.append(patient_number)
        
        index.append('filenumber')
        features.append(filename[filename.find('_')+1:-6])
        
        #accross channels features on full data
        correlation_matrix = np.corrcoef(data)
        correlation_matrix = np.nan_to_num(correlation_matrix)
        # take only values in upper triangle to avoid redundancy
        triup_index = np.triu_indices(16, k=1)
        for i, j in zip(triup_index[0], triup_index[1]):
            features.append(correlation_matrix[i][j])
            index.append(f'correlation_{i}-{j}')

        eigenvals = np.linalg.eigvals(correlation_matrix)
        eigenvals = np.nan_to_num(eigenvals)
        eigenvals = np.real(eigenvals)
        for i in CHANNELS:
            features.append(eigenvals[i])
            index.append(f'eigenval_{i}')
            
        # summed across all channels and frequencies
        summed_energy = total_energy(data_downsampled)
        features.append(summed_energy)
        index.append('summed_energy')
        
        logging.debug('general features generated')
        
        #Per channel features
        #TODO work on all channels in parrallel as one matrix, vectorise all of it
        for c in CHANNELS:
            
            logging.debug(f'starting feature generation file:{counter}, channel:{c}')
            
            # Create necessary functions
            data_channel = data_downsampled[c]
            diff1 = np.diff(data_channel, n=1)
            diff2 = np.diff(data_channel, n=2)

            ## Simple features
            std = np.std(data_channel)
            features.append(std)
            index.append(f'std_{c}')

            skew = scipy.stats.skew(data_channel)
            features.append(skew)
            index.append(f'skew_{c}')

            kurt = scipy.stats.kurtosis(data_channel)
            features.append(kurt)
            index.append(f'kurt_{c}')

            zeros = zero_crossings(data_channel)
            features.append(zeros)
            index.append(f'zeros_{c}')
            
            logging.debug('simple features generated')

            #RMS = np.sqrt(data_channel**2.mean())

            ## Differential features
            mobility = np.std(diff1)/np.std(data_channel)
            features.append(mobility)
            index.append(f'mobility_{c}')

            complexity = (np.std(diff2) * np.std(diff2)) / np.std(diff1)
            features.append(complexity)
            index.append(f'complexity_{c}')

            zeros_diff1 = zero_crossings(diff1)
            features.append(zeros_diff1)
            index.append(f'zeros_diff1_{c}')

            zeros_diff2 = zero_crossings(diff2)
            features.append(zeros_diff2)
            index.append(f'zeros_diff2_{c}')

            std_diff1 = np.std(diff1)
            features.append(std_diff1)
            index.append(f'std_diff1_{c}')

            std_diff2 = np.std(diff2)
            features.append(std_diff2)
            index.append(f'std_diff2_{c}')
            
            logging.debug('differential features generated')

            # Frequency features

            ## Use welch method to approcimate energies per frequency subdivision
            # From litterature the lowest frequencies of interest in a EEG is 0.5Hz so we need to keep our resolution at 0.25Hz hence a 4 second window cf.Nyquist
            window = (SAMPLING_FREQUENCY / DOWNSAMPLING_RATIO) * 4
            f, psd = scipy.signal.welch(data_channel, fs=80, nperseg=window)
            psd = np.nan_to_num(psd)

            ## Total summed energy
            channel_energy = band_energy(f, psd, 0.1, 40)
            features.append(channel_energy)
            index.append(f'channel_{c}_energy')

            ## Normalised summed energy
            normalised_energy = channel_energy / summed_energy
            features.append(normalised_energy)
            index.append(f'normalised_energy_{c}')

            ## Peak frequency
            peak_frequency = f[np.argmax(psd)]
            features.append(peak_frequency)
            index.append(f'peak_frequency_{c}')

            ## Normalised_summed energy per band
            for k in range(len(BANDS)-1):
                energy = band_energy(f, psd, BANDS[k], BANDS[k+1])
                normalised_band_energy = energy / channel_energy
                features.append(normalised_band_energy)
                index.append(f'normalised_band_energy_{c}_{k}')
                
            logging.debug('lowres frequency features generated')

            ## Spectralentropy
            psd_norm = np.divide(psd, psd.sum())
            spectral_entropy = -np.multiply(psd_norm, np.log2(psd_norm)).sum()
            #spectral_entropy /= np.log2(psd_norm.size) #uncomment to normalise entropy
            features.append(spectral_entropy)
            index.append(f'spectral_entropy_{c}')

            ## SVD entropy
            entropy = svd_entropy(data_channel, order=3,
                                  delay=1, normalize=False)
            features.append(entropy)
            index.append(f'svd_entropy_{c}')
            
            logging.debug('entropy features generated')

            # Highres features : energy per frequency band in 1min segements        
            highres_channel_energy = highres_total_energy(data[c]) #TODO check if c should be here
            features.append(highres_channel_energy)
            index.append(f'total_channel_energy_{c}')
            
            f, psd = scipy.signal.welch(data[c], fs=400, nperseg=SAMPLING_FREQUENCY*4)
            psd = np.nan_to_num(psd)
            full_psd_sum = psd.sum()/10  # for normalisation purposed
            # TODO add band energy divided by full_psd_sum as feature
            
            # j allows us to iterate over 1min segments with 30s overlap
            for j in range(19):
                data_segment = data[c][j*30*SAMPLING_FREQUENCY: (j+1)*30*SAMPLING_FREQUENCY]
                f_segment, psd_segment = scipy.signal.welch(
                    data_segment, fs=SAMPLING_FREQUENCY, nperseg=SAMPLING_FREQUENCY*4)
                psd_segment = np.nan_to_num(psd_segment)

                for k in range(len(HIGHRES_BANDS)-1):
                    window_band_energy = psd_segment[(f_segment > HIGHRES_BANDS[k]) & (
                        f_segment < HIGHRES_BANDS[k+1])].sum()
                    features.append(window_band_energy)
                    index.append(f'windowed_band_energy_{c}_{k}_{j}')
                    normalised_window_band_energy = window_band_energy/full_psd_sum
                    features.append(normalised_window_band_energy)
                    index.append(f'normalised_window_band_energy_{c}_{k}_{j}')
                    #TODO check if normalised feature is redundant
                    
            logging.debug('highres frequency features generated')
            
            #logging.debug(f'finished feature generation file:{counter}, channel:{c}')

        # Save generated features to X_train
        if counter == 0:
            #X_train = np.zeros((1, len(features)))
            X = np.array(features)
            logging.debug('X created and updated')   
        else:
            X = np.vstack((X, np.array(features)))
            logging.debug(f'features for file:{counter} added to array ; X.shape = {X.shape}')
        
        # Save label to y_train
        if is_training_data:
            label = filename[-5 : -4] #last char excluding .mat
            if counter == 0:
                y = np.array(label).astype('int')
                logging.debug(' y created and updated')
            else :
                y = np.vstack((y, np.array(label))).astype('int')
                logging.debug(f'label stacked onto y, y.shape = {y.shape}')
        
        counter += 1

        #TODO add logging

    # Save X_train to file before moving on to next patient data
    X = np.nan_to_num(X)
    y = np.nan_to_num(y)
       
    if is_training_data:
        if save_to_disk:
            np.save(join(FEATURE_SAVE_PATH, f'neurovista_X_train_pat{patient_number}.npy'), X)
            np.save(join(FEATURE_SAVE_PATH, f'neurovista_y_train_pat{patient_number}.npy'), y)
            logging.info('features and labels saved to disk')
        return (X, y, index)
    
    if is_training_data == False:
        if save_to_disk:
            np.save(join(FEATURE_SAVE_PATH, f'neurovista_X_test_pat{patient_number}.npy'), X)
            logging.info('features saved to disk')
        return (X, index)
    
#%% Call feature generation on every patient for training data

data_dict = {}

for p in [1, 2, 3]:  #[1, 2, 3]:  # iterating over patients 1, 2, 3

    logging.info(f'Entering loop to generate train features for patient {p}')
    patient_path = join(DATA_PATH, TRAIN_PATHS[p-1])
    
    data_dict[f'X_train_{p}'], data_dict[f'y_train_{p}'], index = generate_features(patient_number = p , data_path = patient_path, is_training_data = True, save_to_disk = True)

#%% call on test data

for p in [1, 2, 3]:  #[1, 2, 3]:  # iterating over patients 1, 2, 3

    logging.info(f'Entering loop to generate test set features for patient {p}')
    patient_path = join(DATA_PATH, TEST_PATHS[p-1])
    
    data_dict[f'X_test_{p}'], index = generate_features(patient_number = p , data_path = patient_path, is_training_data = False, save_to_disk = True)
  
    
#%% fast feature generation for iterating and testing

for p in [1]:  #[1, 2, 3]:  # iterating over patients 1, 2, 3

    logging.info(f'Entering loop to generate train features for patient {p}')
    patient_path = join(DATA_PATH, TRAIN_PATHS[p-1])
    
    X_old, y_old, index_old = generate_features(patient_number = p , data_path = patient_path, is_training_data = True, save_to_disk = False)
#%%

X_old_df = pd.DataFrame(data = X_old, columns = index_old) 
X_old_df.head()
X_old_df.to_csv('X_old.csv' , columns = index_old)
