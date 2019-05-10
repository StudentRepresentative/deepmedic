# Copyright (c) 2016, Konstantinos Kamnitsas
# All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the BSD license. See the accompanying LICENSE file
# or read the terms at https://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, print_function, division

import numpy as np
import scipy.ndimage

# Main function to call:
def augment_images_of_case(channels, gt_lbls, roi_mask, wmaps_per_cat, prms):
    # channels: list (x pathways) of np arrays [channels, x, y, z]. Whole volumes, channels of a case.
    # gt_lbls: np array of shape [x,y,z]. Can be None.
    # roi_mask: np array of shape [x,y,z]. Can be None.
    # wmaps_per_cat: List of np.arrays (floats or ints), weightmaps for sampling. Can be None.
    # prms: None (for no augmentation) or Dictionary with parameters of each augmentation type. }
    if prms is not None:
        channels,
        gt_lbls,
        roi_mask,
        wmaps_per_cat = random_affine_deformation(channels,
                                                  gt_lbls,
                                                  roi_mask,
                                                  wmaps_per_cat,
                                                  prms['affine'])
    return channels, gt_lbls, roi_mask, wmaps_per_cat


class AugmenterParams(object):
    # Parent class, for parameters of augmenters.
    def __init__(self):
        self._prms = {}
        
    def __init__(self, prms):
        self.__init__()
        self.set_from_dict(prms)
        
    def __str__(self):
        return str(self._prms)
    
    def __getitem__(self, key): # overriding the [] operator.
        # key: string.
        return self._prms[key] if key in self._prms else None
    
    def __setitem__(self, key, item): # For instance[key] = item assignment
        self._prms[key] = item
        
    def set_from_dict(self, prms):
        for key in prms.keys():
            self._prms[key] = prms[key]
            
            
def random_affine_deformation(channels, gt_lbls, roi_mask, wmaps_l, prms):
    augm = AugmenterAffineDeformation( prob=prms['prob'],
                                       max_rot_x=prms['max_rot_x'],
                                       max_rot_y=prms['max_rot_y'],
                                       max_rot_z=prms['max_rot_z'],
                                       max_scaling=prms['max_scaling'],
                                       seed=prms['seed'] )
    transf_mtx = augm.roll_dice_and_get_random_transformation()
    assert transf_mtx is not None
    
    channels  = augm(transf_mtx = transf_mtx,
                     images_l = channels,
                     interp_orders = prms['interp_order_imgs'],
                     boundary_modes = prms['boundary_mode'])
    (gt_lbls,
    roi_mask) = augm(transf_mtx = transf_mtx,
                     images_l = [gt_lbls, roi_mask],
                     interp_orders = [prms['interp_order_lbls'], prms['interp_order_roi']],
                     boundary_modes = prms['boundary_mode'])
    wmaps_l   = augm(transf_mtx = transf_mtx,
                     images_l = wmaps_per_cat,
                     interp_orders = prms['interp_order_wmaps'],
                     boundary_modes = prms['boundary_mode'])

    return channels, gt_lbls, roi_mask, wmaps_l


class AugmenterAffineDeformationParams(AugmenterParams):
    def __init__(self):
        self._prms = { # For init.
                       'prob': 0.5,
                       'max_rot_x': 10.0,
                       'max_rot_y': 10.0,
                       'max_rot_z': 10.0,
                       'max_scaling': .1,
                       'seed': 64,
                       # For calls.
                       'interp_order_imgs': 1,
                       'interp_order_lbls': 0,
                       'interp_order_roi': 0,
                       'interp_order_wmaps': 1,
                       'boundary_mode': 'nearest',
                       'cval': 0. }



class AugmenterAffineDeformation(object):
    def __init__(self, prob, max_rot_x, max_rot_y, max_rot_z, max_scaling, seed=64):
        self.prob = prob # Probability of applying the transformation.
        self.max_rot_x = max_rot_x
        self.max_rot_y = max_rot_y
        self.max_rot_z = max_rot_z
        self.max_scaling = max_scaling
        self.rng = np.random.RandomState(seed)

    def roll_dice_and_get_random_transformation(self):
        if self.rng.random_sample() > self.prob:
            return -1 # No augmentation
        else:
            return self._get_random_transformation() #transformation for augmentation
        
    def _get_random_transformation(self):
        theta_x = self.rng.uniform(-self.max_rot_x, self.max_rot_x) * np.pi / 180.
        rot_x = np.array([ [np.cos(theta_x), -np.sin(theta_x), 0.],
                           [np.sin(theta_x), np.cos(theta_x), 0.],
                           [0., 0., 1.]])
        
        theta_y = self.rng.uniform(-self.max_rot_y, self.max_rot_y) * np.pi / 180.
        rot_y = np.array([ [np.cos(theta_y), 0., np.sin(theta_y)],
                           [0., 1., 0.],
                           [-np.sin(theta_y), 0., np.cos(theta_y)]])
        
        theta_z = self.rng.uniform(-self.max_rot_z, self.max_rot_z) * np.pi / 180.
        rot_z = np.array([ [1., 0., 0.],
                           [0., np.cos(theta_z), -np.sin(theta_z)],
                           [0., np.sin(theta_z), np.cos(theta_z)]])
        
        # Sample the scale (zoom in/out)
        # TODO: Non isotropic?
        scale = np.eye(3, 3) * self.rng.uniform(1 - self.max_scaling, 1 + self.max_scaling)
        
        # Affine transformation matrix.
        transformation_mtx = np.dot( scale, np.dot(rot_z, np.dot(rot_x, rot_y)) )
        
        return transformation_mtx

    def _apply_transformation(self, image, transf_mtx, interp_order=3., boundary_mode='nearest', cval=0.):
        # image should be 3 dimensional (Height, Width, Depth). Not multi-channel.
        # interp_order: Integer. 3 for images, 0 for nearest neighbour on masks (GT & brainmasks)
        # boundary_mode = 'constant', 'min', 'nearest', 'mirror...
        # cval: float. value given to boundaries if mode is constant.
        mode = boundary_mode
        if mode == 'min':
            cval = np.min(image)
            mode = 'constant'
        
        # For recentering
        centre_coords = 0.5 * np.asarray(image.shape, dtype=np.int32)
        c_offset = centre_coords - centre_coords.dot( transf_mtx )
        
        new_image = scipy.ndimage.affine_transform( image,
                                                    transf_mtx.T,
                                                    c_offset,
                                                    order=interp_order,
                                                    mode=mode,
                                                    cval=cval )
        return new_image
    
    def __call__(self, transf_mtx, images_l, interp_orders, boundary_modes, cval=None):
        # transf_mtx: Given (from get_random_transformation), -1, or None.
        #             If -1, no augmentation/transformation will be done.
        #             If None, new random will be made.
        # images_l : List of images, or an array, where first dimension is over images (eg channels).
        #            An image (element of the var) can be None, and it will be returned unchanged.
        # intrp_orders : Int or List of integers. Orders of bsplines for interpolation, one per image in images_l.
        #                Suggested: 3 for images. 1 is like linear. 0 for masks/labels, like NN.
        # boundary_mode = String or list of strings. 'constant', 'min', 'nearest', 'mirror...
        # cval: single float value. Value given to boundaries if mode is constant.

        if transf_mtx is None: # Get random transformation.
            transf_mtx = self.roll_dice_and_get_random_transformation()
        if transf_mtx == -1: # Do not augment
            return images_l
        
        # If scalars/string was given, change it to list of scalars/strings, per image.
        if isinstance(interp_orders, int):
            interp_orders = [interp_orders] * len(images_l)
        if isinstance(boundary_modes, str):
            boundary_modes = [boundary_modes] * len(images_l)
        
        # Deform images.
        new_images_l = []
        for image, interp_order, boundary_mode in zip(images_l, interp_orders, boundary_modes):
            if image is None:
                new_images_l.append(image)
            else:
                new_images_l.append( self._apply_transformation(image,
                                                                transf_mtx,
                                                                interp_order,
                                                                boundary_mode,
                                                                cval)
                                    )
        return new_images_l



############# Currently not used ####################

# DON'T use on patches. Only on images. Cause I ll need to find min and max intensities, to move to range [0,1]
def random_gamma_correction(channels, gamma_std=0.05):
    # Gamma correction: I' = I^gamma
    # channels: list (x pathways) of np arrays [channels, x, y, z]. Whole volumes, channels of a case.
    # IMPORTANT: Does not work if intensities go to negatives.
    if gamma_std is None or gamma_std == 0.:
        return channels
    
    n_channs = channels[0].shape[0]
    gamma = np.random.normal(1, gamma_std, [n_channs,1,1,1])
    for path_idx in range(len(channels)):
        assert np.min(channels[path_idx]) >= 0.
        channels[path_idx] = np.power(channels[path_idx], 1.5, dtype='float32')
        
    return channels



            