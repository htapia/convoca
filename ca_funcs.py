import numpy as np
import matplotlib.pyplot as plt
import tensorflow as tf
import collections

from itertools import product

# from utils import *


def make_table_walk(nbins, known_rule=''):
    '''
    Walk across a table of CA rules, changing one 
    index at a time. When a specific rules is given, incorporate it into the walk
    
    nbins : the number of rules, and entries
    
    known_rule : np.array, a known rule to include (consisting of ones and zeros)
    
    
    Dev: 
    - Work with list of rules rather than just one or zero specified rules
    - Check ordering of the rules; right now this only takes the outputs of the
    truth table and assumes the ordering generated by "all_combinations"
    - A better algorithm would traverse the rule list in one loop and draw 
    indices to hit from different, non-overlapping sets based on the current index
    value. Probably not much performance boost though, but at least conceptually
    simpler
    '''
    
    selection_order = np.random.choice(range(nbins), nbins, replace=False)
    
    all_rules = np.zeros((nbins,nbins))
    
    if len(known_rule)==0:
        for ind in range(len(all_rules)):
            all_rules[ind:, selection_order[ind]] = 1
    else:
        
        num_on = int(np.sum(known_rule))
        num_off = int(nbins - num_on)

        where_on = np.where(known_rule==1)[0]
        where_off = np.where(~(known_rule==1))[0]
        
        assert num_on==len(where_on)
        assert num_off==len(where_off)
        
        selection_order_indices = np.random.choice(range(num_on), num_on, replace=False)
        selection_order = where_on[selection_order_indices]
        for ind in range(len(selection_order)):
            all_rules[ind:, selection_order[ind]] = 1
            
    
        selection_order_indices = np.random.choice(range(num_off), num_off, replace=False)
        selection_order = where_off[selection_order_indices]
        for ind in range(len(selection_order)):
            all_rules[num_on+ind:, selection_order[ind]] = 1
   
    return all_rules
   

def get_network_entropies(feature_map):
    '''
    Given a list of directories containing fully-trained models, find the 
    entropy of single-neuron firings, layer firings, and layer group firings
    in order to assess independence 
    
    feature_map : list of lists
        A list of firing patterns
        (layer index, )

    DEV: collections.Counter is actually faster than using the np.unique
    function, could try setting a global flag for Counter when the script is 
    first loaded, and then use it if it is available?

    '''
    
    neuron_ent = [layer_entropy(thing) for thing in feature_map]
    
    all_layer_ents = list()
    all_patterns = list()


    for layer in feature_map:
        flat_out = (np.reshape(layer, (-1,layer.shape[-1]))).astype(int)
        all_patterns.append(flat_out)
        vals, counts = np.unique(flat_out, axis=0, return_counts=True)
        counts = counts/np.sum(counts)
        all_layer_ents.append(shannon_entropy(counts))

    layer_ent = all_layer_ents

    whole_pattern = np.hstack(all_patterns)
    vals, counts = np.unique(whole_pattern, axis=0, return_counts=True)
    counts = counts/np.sum(counts)
    whole_ent = shannon_entropy(counts)

    out = (whole_ent, layer_ent, neuron_ent)  
    return out

def periodic_padding(image, padding=1):
    '''
    Create a periodic padding (wrap) around an image stack, to emulate periodic boundary conditions
    Adapted from https://github.com/tensorflow/tensorflow/issues/956
    
    If the image is 3-dimensional (like an image batch), padding occurs along the last two axes
    
    
    '''
    if len(image.shape)==2:
        upper_pad = image[-padding:,:]
        lower_pad = image[:padding,:]

        partial_image = tf.concat([upper_pad, image, lower_pad], axis=0)

        left_pad = partial_image[:,-padding:]
        right_pad = partial_image[:,:padding]

        padded_image = tf.concat([left_pad, partial_image, right_pad], axis=1)
        
    elif len(image.shape)==3:
        upper_pad = image[:,-padding:,:]
        lower_pad = image[:,:padding,:]

        partial_image = tf.concat([upper_pad, image, lower_pad], axis=1)

        left_pad = partial_image[:,:,-padding:]
        right_pad = partial_image[:,:,:padding]

        padded_image = tf.concat([left_pad, partial_image, right_pad], axis=2)
        
        
    else:
        assert True, "Input data shape not understood."
    
    return padded_image


def conv_cast(arr, cast_type=tf.float32):
    return tf.cast(tf.convert_to_tensor(arr), cast_type)

def arr2tf(arr, var_type='None'):
    '''Given np.array, convert to a float32 tensor
    
    var_type: 'var' or 'const'
        Whether the created variable is a constant of fixed
        
    '''
    
    arr_tf = tf.convert_to_tensor(arr)
    
    if var_type=='const':
        arr_tf = tf.constant(arr_tf)
    elif var_type=='var':
        arr_tf = tf.Variable(arr_tf)
    else:
        pass
    
    out = tf.cast(arr_tf, tf.float32)
    
    return out

def categorize_images(image_stack, neighborhood="von neumann"):
    '''
    Given an MxNxN stack of numpy images, performs periodic convolution with an SxSxT
    stack of kernels to produce an MxNxN output representing which of the T classes
    each pixel belongs to. Each class represents a distinct neighborhood arrangement 
    around that point

    This function may be used to find the prior distribution of inputs in an image
    
    Returns
    -------
    
    indices : tf.Tensor. Corresponds to the T labels for each pixel in the original
    image stack
    
    '''
    
    if neighborhood=="von neumann":
        pad_size = 1
        all_filters = np.transpose(all_combinations(2,d=9), (2,1,0))
        all_biases = 1-np.sum(all_filters,axis=(0,1))
        all_filters[all_filters==0] -= np.prod(all_filters.shape[:2])
    else:
        assert True, "Specified neighborhood type not implemented"
    
    state = conv_cast(image_stack)
    kernel = conv_cast(all_filters)[:,:,tf.newaxis,:]
    biases = conv_cast(all_biases)

    input_padded = periodic_padding(state, pad_size)[...,tf.newaxis]

    conv_image = tf.nn.conv2d(input_padded, kernel, strides=[1,1,1,1], padding='VALID')
    
    # last axis is one-hot representation telling us which of the D^M states we are in
    activation_image = tf.nn.relu(conv_image + biases)

    indices = tf.argmax(activation_image, axis=-1)
    
    return indices


def image_entropy(im_stack, neighborhood="von neumann"):
    '''
    Given a stack of images, compute the entropy of the symbol distribution for
    each image. Currently, this function assumes a von Neumann neighborhood
    around each pixel
    
    im_stack : MxNxN np.array, where M indexes the image batch
        and NxN are the image dimensions
        
    Development
    -----------
    
    It would be nice if this whole process was pure Tensorflow, for speed
    
    '''
    
    categ_im = categorize_images(im_stack)

    if tf.executing_eagerly():
        categ_im_arr = categ_im.numpy()
    else:
        categ_im_arr = categ_im.eval()
        
    flat_categs = np.reshape(categ_im_arr,(categ_im_arr.shape[0], np.prod(categ_im_arr.shape[-2:])))
    
    all_ents = np.zeros(flat_categs.shape[0])
    
    for ind, flat_thing in enumerate(flat_categs):
        unique_keys, counts = np.unique(flat_thing, return_counts=True) 
        counts = counts.astype(float)
        # dict(zip(unique_keys, counts)) # make histogram dict

        counts /= np.sum(counts)    # normalize
        ent = shannon_entropy(counts)

        all_ents[ind] = ent
        
    return all_ents
    


def make_ca(words, symbols, neighborhood="von neumann"):
    '''
    Build an arbitrary cellular automaton in tensorflow
    The CA will take images of the form MxNxN as input,
    where M is the batch size and NxN is the image dimensions
    
    CA states are formulated as individual "rules" based 
    on pattern matching 2^D = 2^9 single inputs
    
    Inputs
    ------
    
    words: iterable of M x (...) input states corresponding to the 
    rule table for the CA
    
    symbols : M-vector of assignments (next states) for each of the
    words, in the same order as the words vector
    
    Returns
    -------
    
    my_ca : func. A function in Tensorflow
    
    Development
    -----------
    
    Test to ensure that the generated function performs in both
    eager and traditional tensorflow environments
    
    '''
    
    # this may not be true for a non-binary CA; generalize this later
    all_filters = words
    state_assignments = symbols
    
    
    if neighborhood=="von neumann":
        pad_size = 1
        all_filters = np.transpose(all_combinations(2,d=9), (2,1,0))
        all_biases = 1-np.sum(all_filters,axis=(0,1))
        all_filters[all_filters==0] -= np.prod(all_filters.shape[:2])
    else:
        assert True, "Specified neighborhood type not implemented"
    
    kernel = conv_cast(all_filters)[:,:,tf.newaxis,:]
    biases = conv_cast(all_biases)
    state_assignments = conv_cast(state_assignments)
    def my_ca(image_stack):
        '''
        Automatically generated function created by make_ca()
        Input array must already be a tensor when fed to the function
        '''
        input_padded = periodic_padding(image_stack, pad_size)[...,tf.newaxis]

        conv_image = tf.nn.conv2d(input_padded, kernel, strides=[1,1,1,1], padding='VALID')

        # last axis is one-hot representation telling us which of the D^M states we are in
        activation_image = tf.nn.relu(conv_image + biases)
        
        #next_states = tf.matmul(activation_image, tf.expand_dims(state_assignments,1))
        next_states = tf.reduce_sum(tf.multiply(activation_image, state_assignments[tf.newaxis,:]),  axis=-1)
        
        return next_states

    return my_ca


def make_game_of_life():
    '''
    Returns a simplified Tensorflow implementation of Conway's Game of Life
    '''
    
    neighborhood_radius = 3
    pad_size = 1

    neighbor_filt = np.ones((neighborhood_radius,neighborhood_radius))
    neighbor_filt[1,1] = 0
    middle_filt = np.zeros((neighborhood_radius,neighborhood_radius))
    middle_filt[1,1] = 1
    all_filters = np.dstack((middle_filt, neighbor_filt, neighbor_filt, neighbor_filt, neighbor_filt))
    all_biases = np.array([0,  -1, -2, -3, -4]) 
    total_filters = len(all_biases)
    kernel = conv_cast(all_filters)[:,:,tf.newaxis,:]
    biases = conv_cast(all_biases)
    
    wh1_arr = np.array([
    [0, 0, 4/3, -8/3, -1/3],
    [3/2, 5/4, -5, -1/4, -1/4]
    ]).T
    bh1_arr = np.array([-1/3,-7/4]).T
    wh1 = conv_cast(wh1_arr)
    bh1 = conv_cast(bh1_arr)
    
    def my_ca(image_stack):
        '''
        Automatically generated function created by make_ca()
        Input array must already be a tensor when fed to the function
        '''
        input_padded = periodic_padding(image_stack, pad_size)[...,tf.newaxis]

        conv_image = tf.nn.conv2d(input_padded, kernel, strides=[1,1,1,1], padding='VALID')

        activation_image = tf.nn.relu(conv_image + biases)

        activated_flat = tf.reshape(activation_image, [-1, total_filters])
        
        h1 = tf.nn.relu(tf.matmul(activated_flat, wh1) + bh1)

        scores = tf.reduce_sum(h1, axis=-1)
        next_states = tf.reshape(scores, [*activation_image.shape[:3],1])
        
        return tf.squeeze(next_states)

    return my_ca



def make_glider(dims0):
    """
    Produce Glider initial conditions for Conway's Game of Life
    
    dims0 : int, float, or length 2 iterable
    
    """

    dims = np.ravel(np.array([dims0]))
    
    if len(dims)==1:
        dims = np.squeeze([dims, dims])
    dims = np.array(dims)
    
    # Check that provided dimensions are large enough
    for item in dims:
        assert item >= 3
    
    glider_center = np.array([[0,1,0],
                              [0,0,1],
                              [1,1,1]])
    
    ins_inds = np.floor(dims/2).astype(int)

    out_arr = np.zeros(dims)
    out_arr[ins_inds[0]-1:ins_inds[0]+2, ins_inds[1]-1:ins_inds[1]+2] = glider_center
    
    return out_arr
