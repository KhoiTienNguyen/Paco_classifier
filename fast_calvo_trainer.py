# -----------------------------------------------------------------------------
# Program Name:         calvo_trainer.py
# Program Description:  Rodan wrapper for Fast Calvo's classifier training
# -----------------------------------------------------------------------------

import cv2
import logging
import numpy as np
import os
import sys

from rodan.celery import app
from celery.utils.log import get_task_logger
from rodan.jobs.base import RodanTask
from . import training_engine_sae as training

"""Wrap Patchwise (Fast) Calvo classifier training in Rodan."""

logger = get_task_logger(__name__)


class FastCalvoTrainer(RodanTask):
    name = "Training model for Patchwise Analysis of Music Document"
    author = "Jorge Calvo-Zaragoza, Francisco J. Castellanos, Gabriel Vigliensoni, and Ichiro Fujinaga"
    description = "The job performs the training of many Selection Auto-Encoder model for the pixelwise analysis of music document images."
    enabled = True
    category = "OMR - Layout analysis"
    interactive = False

    settings = {
        'title': 'Training parameters',
        'type': 'object',
        'properties': {
            'Batch Size': {
                'type': 'integer',
                'minimum': 1,
                'default': 16,
                'maximum': 64,
            },
            'Maximum number of training epochs': {
                'type': 'integer',
                'minimum': 1,
                'default': 15
            },
            'Maximum number of samples per label': {
                'type': 'integer',
                'minimum': 100,
                'default': 2000
            },            
            'Patch height': {
                'type': 'integer',
                'minimum': 32,
                'default': 256
            },
            'Patch width': {
                'type': 'integer',
                'minimum': 32,
                'default': 256
            },
        },
        'job_queue': 'GPU'
    }

    input_port_types = (
        {'name': 'Image', 'minimum': 1, 'maximum': 1, 'resource_types': ['image/rgb+png','image/rgb+jpg']},
        {'name': 'rgba PNG - Background layer', 'minimum': 1, 'maximum': 1, 'resource_types': ['image/rgba+png']},
        {'name': 'rgba PNG - Music symbol layer', 'minimum': 1, 'maximum': 1, 'resource_types': ['image/rgba+png']},
        {'name': 'rgba PNG - Selected regions', 'minimum': 1, 'maximum': 1, 'resource_types': ['image/rgba+png']},
        # Optional ports
        {'name': 'rgba PNG - Staff Lines layer', 'minimum': 0, 'maximum': 1, 'resource_types': ['image/rgba+png']},
        {'name': 'rgba PNG - Text', 'minimum': 0, 'maximum': 1, 'resource_types': ['image/rgba+png']},
    )

    output_port_types = (
        {'name': 'Background Model', 'minimum': 1, 'maximum': 1, 'resource_types': ['keras/model+hdf5']},
        {'name': 'Music Symbol Model', 'minimum': 1, 'maximum': 1, 'resource_types': ['keras/model+hdf5']},
        {'name': 'Log File', 'minimum': 1, 'maximum': 1, 'resource_types': ['text/plain']},
        # Optional ports
        {'name': 'Staff Lines Model', 'minimum': 0, 'maximum': 1, 'resource_types': ['keras/model+hdf5']},
        {'name': 'Text Model', 'minimum': 0, 'maximum': 1, 'resource_types': ['keras/model+hdf5']},
    )


    def run_my_task(self, inputs, settings, outputs):
        oldouts = sys.stdout, sys.stderr
        if len(outputs['Log File']) > 0:
            handler = logging.FileHandler(outputs['Log File'][0]['resource_path'])
            handler.setFormatter(
                logging.Formatter('%(asctime)s - %(name)s - %(message)s')
            )
            logger.addHandler(handler)
        try:
            rlevel = app.conf.CELERY_REDIRECT_STDOUTS_LEVEL
            app.log.redirect_stdouts_to_logger(logger, rlevel)

            # Ports
            input_image = cv2.imread(inputs['Image'][0]['resource_path'], True) # 3-channel
            background = cv2.imread(inputs['rgba PNG - Background layer'][0]['resource_path'], cv2.IMREAD_UNCHANGED) # 4-channel
            notes = cv2.imread(inputs['rgba PNG - Music symbol layer'][0]['resource_path'], cv2.IMREAD_UNCHANGED) # 4-channel
            regions = cv2.imread(inputs['rgba PNG - Selected regions'][0]['resource_path'], cv2.IMREAD_UNCHANGED) # 4-channel

            # Create categorical ground-truth
            gt = {}
            regions_mask = (regions[:, :, 3] == 255)
            notes_mask = (notes[:, :, 3] == 255)
            gt['symbols'] = np.logical_and(notes_mask, regions_mask) # restrict layer to only the notes in the selected regions
            gt['background'] = (background[:, :, 3] == 255) # background is already restricted to the selected regions (based on Pixel.js' behaviour)

            # Settings
            batch_size = settings['Batch Size']
            patch_height = settings['Patch height']
            patch_width = settings['Patch width']
            max_number_of_epochs = settings['Maximum number of training epochs']
            max_samples_per_class = settings['Maximum number of samples per label']

            output_models_path = {
                'background': outputs['Background Model'][0]['resource_path'],
                'symbols': outputs['Music Symbol Model'][0]['resource_path'],
            }

            # optional layers
            for k in inputs:
                if k == 'rgba PNG - Staff Lines layer':
                    lines = cv2.imread(inputs['rgba PNG - Staff Lines layer'][0]['resource_path'], cv2.IMREAD_UNCHANGED) # 4-channel
                    lines_mask = (lines[:, :, 3] == 255)
                    gt['staff'] = np.logical_and(lines_mask, regions_mask) # restrict layer to only the staff lines in the selected regions
                if k == 'rgba PNG - Text':
                    text = cv2.imread(inputs['rgba PNG - Text'][0]['resource_path'], cv2.IMREAD_UNCHANGED) # 4-channel
                    text_mask = (text[:, :, 3] == 255)
                    gt['text'] = np.logical_and(text_mask, regions_mask) # restrict layer to only the text in the selected regions

            for k in outputs:
                if k == 'Staff Lines Model':
                    output_models_path['staff'] = outputs['Staff Lines Model'][0]['resource_path']
                if k == 'Text Model':
                    output_models_path['text'] = outputs['Text Model'][0]['resource_path']

            # Call in training function
            status = training.train_msae(
                input_image=input_image,
                gt=gt,
                height=patch_height,
                width=patch_width,
                output_path=output_models_path,
                epochs=max_number_of_epochs,
                max_samples_per_class=max_samples_per_class,
                batch_size=batch_size,
            )

            print('Finishing the Fast CM trainer job.')
            return True
        finally:
            sys.stdout, sys.stderr = oldouts

    def my_error_information(self, exc, traceback):
        pass
