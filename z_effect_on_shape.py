import os
HOME = os.environ["HOME"]
os.environ["CARDIAC_GWAS_REPO"] = CARDIAC_GWAS_REPO = f"{HOME}/01_repos/CardiacGWAS"
os.environ["CARDIAC_COMA_REPO"] = CARDIAC_COMA_REPO = f"{HOME}/01_repos/CardiacCOMA/"
os.environ["GWAS_REPO"] = GWAS_REPO = f"{HOME}/01_repos/GWAS_pipeline/"

MLRUNS_DIR = f"{CARDIAC_COMA_REPO}/mlruns"
#os.chdir(CARDIAC_COMA_REPO)

import mlflow
from mlflow.tracking import MlflowClient

import os, sys

import torch
import torch.nn.functional as F

from CardiacCOMA.config.cli_args import overwrite_config_items
from CardiacCOMA.config.load_config import load_yaml_config, to_dict
from CardiacCOMA.utils.helpers import get_datamodule, get_lightning_module
from CardiacCOMA.utils.mlflow_helpers import get_model_pretrained_weights
from CardiacCOMA.utils.CardioMesh.CardiacMesh import transform_mesh

import ipywidgets as widgets
from ipywidgets import interact
from IPython.display import Image, display, Markdown, clear_output

import pandas as pd
import shlex
from subprocess import check_output

import pickle as pkl
import pytorch_lightning as pl

from argparse import Namespace
import matplotlib.pyplot as plt

import numpy as np
import pandas as pd
from IPython import embed
sys.path.insert(0, '..')

from copy import deepcopy
from pprint import pprint

from typing import List
from tqdm import tqdm

import pandas as pd

import pyvista as pv
from ipywidgets import interact, interactive, fixed, interact_manual

from auxiliary import load_data
from auxiliary import get_model_pretrained_weights
from typing import Sequence, Dict

from PIL import Image
import imageio
import random


def load_mesh_data():
    
    global meshes, procrustes_transforms
    print("Loading mesh data...")
    meshes = pkl.load(open(f"{CARDIAC_COMA_REPO}/data/cardio/LV_meshes_at_ED_35k.pkl", "rb"))
    print("Mesh data loaded successfully.")
    
    print("Loading Procrustes transforms...")
    procrustes_transforms = pkl.load(open(f"{CARDIAC_COMA_REPO}/data/cardio/procrustes_transforms_35k.pkl", "rb"))
    print("Procrustes transform loaded successfully.")
    

def merge_pngs(pngs, output_png, how):
    # https://www.tutorialspoint.com/python_pillow/Python_pillow_merging_images.htm
    
    # Read images    
    images = [Image.open(png) for png in pngs]    
    
    x_sizes = [image.size[0] for image in images]
    y_sizes = [image.size[1] for image in images]
    
    if how == "vertically":      
      y_size = sum(y_sizes)  
      x_size = images[0].size[0]      
      y_sizes.insert(0, 0)      
      y_positions = np.cumsum(y_sizes[:-1])    
      positions = [(0, y_position) for y_position in y_positions]
    
    elif how == "horizontally":
      x_size = sum(x_sizes)      
      y_size = images[0].size[1]      
      x_sizes.insert(0, 0)      
      x_positions = np.cumsum(x_sizes[:-1])    
      positions = [(x_position, 0) for x_position in x_positions]
    
    
    new_image = Image.new(
        mode='RGB',
        size=(x_size, y_size),
        color=(250, 250, 250)
    )
    
    for i, image in enumerate(images):        
        new_image.paste(image, positions[i])
        
    new_image.save(output_png, "PNG")



def get_ids_in_range(z: pd.Series, q0: float, q1: float):
    '''
      z: pd.Series 
      q0, q1: quantile bounds (q0 < q1, between 0 and 1)    
    '''
        
    z_bounds = z.quantile([q0, q1])    
    ids_in_range = z[(z_bounds[q0] < z) & (z < z_bounds[q1])].index
    
    # coerce id's to string and convert to list
    ids_in_range = [str(id) for id in ids_in_range]
    
    return ids_in_range


def avg_shape_in_q_range(
        meshes: Dict[str, np.array], 
        rmsd: Dict[str, float],
        quantile_range: tuple[float], 
        run_id: str, z: str, exp_id: str ="1"
    ):
    
    '''
    meshes: np.array with dimension N x 3.
    quantile_range: a tuple with two quantiles (floats between 0 and 1 representing).
    z: name of the z variable (*not* the values) 
    '''
    
    z_filepath = f"{MLRUNS_DIR}/{exp_id}/{run_id}/artifacts/output/latent_vector.csv"
    z = pd.read_csv(z_filepath).set_index("ID")[z]
    
    ids_in_range = get_ids_in_range(z, q0, q1)
    
    avg_mesh = np.array([meshes[id] / rmsd[id] for id in ids_in_range]).mean(0)
    rmsd_in_range = np.array([rmsd[id] for id in ids_in_range]).mean()
    avg_mesh = avg_mesh * rmsd_in_range
        
    return avg_mesh 


def plot_mesh(mesh, faces, ofilename):#, camera=(300, 0.0, 0.0):
    
    pv.set_plot_theme("document")
    pl = pv.Plotter(off_screen=True, notebook=False)
    
    pl.camera.position = (300, 0.0, 0.0)
    pl.camera.azimuth = 95
        
    mesh = pv.PolyData(mesh, faces)
    
    pl.add_mesh(
        mesh, show_edges=False, point_size=1.5, color=color_palette[0], opacity=0.5
    )
    
    pl.screenshot(ofilename)

  
# pv.set_plot_theme("document")
# color_palette = list(pv.colors.color_names.values())
# random.shuffle(color_palette)


if __name__ == "__main__":

    VERBOSE = False
    
    load_mesh_data()
    
    good_runs_df = pd.read_csv(f"{CARDIAC_GWAS_REPO}/results/good_runs.csv")
    run_ids = good_runs_df.run_id.to_list()
    
    ids = [ str(id) for id in meshes ] 
    
    faces, _ = pkl.load(open(f"{CARDIAC_COMA_REPO}/data/cardio/faces_and_downsampling_mtx_frac_0.1_LV.pkl", "rb")).values()
    faces = np.c_[np.ones(faces.shape[0]) * 3, faces].astype(int)
            
    aligned_meshes = pkl.load(open("lved_aligned_meshes.pkl", "rb"))
    rmsd = pkl.load(open("lved_rmsd.pkl", "rb"))
                            
    
    for run_id in sorted(os.listdir(f"{CARDIAC_COMA_REPO}/mlruns/1")):
        
        try:
            z_filepath = f"{MLRUNS_DIR}/{exp_id}/{run_id}/artifacts/output/latent_vector.csv"
            zs = pd.read_csv(z_filepath, index_col="ID").columns
        except:
            continue
            
        for z in zs:
                
            z_effect_figs_dir = f"{CARDIAC_COMA_REPO}/mlruns/1/{run_id}/artifacts/z_effect_on_shape"
            os.makedirs(z_effect_figs_dir, exist_ok=True)
            
            filenames = { 
                (q0, q1): f"{z_effect_figs_dir}/{z}_{q0}-{q1}.png" for q0, q1 in q_ranges 
            }
        
            for (q0, q1), filename in filenames.items():
                  
                if os.path.exists(filename):
                    if VERBOSE: print(f"File {filename} already exists.")
                    continue                        
                
                avg_mesh = avg_shape_in_q_range(                
                    meshes=aligned_meshes,
                    rmsd=rmsd,
                    quantile_range=(q0, q1),             
                    exp_id=exp_id,
                    run_id=run_id,
                    z=z,            
                )  
                
                if np.isnan(avg_mesh).all(): break
                
                # print(f"{run_id[:5]}/{z}")
                
                ofilename = filenames[(q0, q1)]
                plot_mesh(avg_mesh, faces, ofilename)                                    
               
            try:            
                filename = f"{z_effect_figs_dir}/{z}.png"
                if not os.path.exists(filename):
                    merge_pngs(filenames.values(), output_png=filename, how="horizontally")
            except:
                pass
    
            
        print(f"{run_id[:5]}")