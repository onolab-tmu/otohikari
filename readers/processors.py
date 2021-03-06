'''
The objects defined in this file are meant to run
some kind of processing on a video in a streaming fashion.

They should have a `process` method that can get called on
a frame or a stack of frame. A frame is a 3d-array of size
(height, width, n_colors), where n_colors is the number of color
channels, usually this is 3 (RGB). A stack of frame has one or more
extra dimensions in the front
'''

import numpy as np
from collections import deque
import time

class ProcessorBase(object):
    '''
    Base class for online processing objects

    The derived classes should implement the __process__ method.
    '''

    def __init__(self, monitor=False, qlen=10):
        self.monitor = monitor

        self.deltas = deque([], qlen)  # list of time delta between two batch of frames
        self.avg_fps = 0.

        self.monitor_freq = 0.5  # print new message every second

        self.total_frames = 0
        self.start = time.perf_counter()
        self.runtime = 0.

        self.frames_since_last_call = 0
        self.last_print = self.start

    def get_fps(self):
        return self.total_frames / self.runtime

    def print_perf(self):
        print('{} frames processed in {} seconds (fps: {:7.3f})'.format(
            self.total_frames, self.runtime, self.get_fps()))

    def __process__(self, frames):
        # dummy process method
        return

    def __call__(self, frames):

        # do the work
        self.__process__(frames)

        if self.monitor:

            # now measure the frame rate
            if frames.ndim == 3:
                n_frames = 1
            elif frames.ndim > 3:
                n_frames = np.prod(frames.shape[:-3])

            self.frames_since_last_call += n_frames
            self.total_frames += n_frames

            now = time.perf_counter()

            delta = now - self.last_print
            self.runtime = now - self.start

            if delta > self.monitor_freq:

                self.deltas.appendleft( (delta, self.frames_since_last_call) )

                avg_fps = np.mean([ n / d for d, n in self.deltas ])

                print('avg fps: {:7.3f}'.format(avg_fps), end='\r')

                self.last_print = now
                self.frames_since_last_call = 0


class OnlineStats(ProcessorBase):
    '''
    Compute statistics on the input data in an online way

    Parameters
    ----------
    shape: tuple of int
        Shape of a data point tensor

    Attributes
    ----------
    mean: array_like (shape)
        Mean of all input samples
    var: array_like (shape)
        Variance of all input samples
    count: int
        Sample size
    '''

    def __init__(self, shape, monitor=False):
        '''
        Initialize everything to zero
        '''
        # call parent method
        ProcessorBase.__init__(self, monitor=monitor)
        
        self.shape = shape
        self.mean = np.zeros(shape, dtype=np.float64)
        self.var = np.zeros(shape, dtype=np.float64)
        self.count = 0

    def __process__(self, data):
        '''
        Update statistics with new data

        Parameters
        ----------
        data: array_like
            A collection of new data points of the correct shape in an array
            where the first dimension goes along the data points
        '''

        if data.shape[-len(self.shape):] != self.shape:
            raise ValueError('The data.shape[1:] should match the statistics object shape')

        data.reshape((-1,) + self.shape)

        count = data.shape[0]
        mean = np.mean(data, axis=0)
        var = np.var(data, axis=0)

        m1 = self.var * (self.count - 1)
        m2 = var * (count - 1)
        M2 = m1 + m2 + (self.mean - mean) ** 2 * count * self.count / (count + self.count)

        self.mean = (count * mean + self.count * self.mean) / (count + self.count)
        self.count += count
        self.var = M2 / (self.count - 1)

class PixelCatcher(ProcessorBase):
    '''
    This is a simple object that collect the values of a few pixels on the stream of frames

    Parameters
    ----------
    pixels: list of tuples
        The location of the pixels to collect in the image
    '''
    def __init__(self, pixels, monitor=False):

        # call parent method
        ProcessorBase.__init__(self, monitor=monitor)
        
        self.pixels = pixels
        self.values = []

    def __process__(self, frames):
        '''
        Catch the values of the pixels in a stack of frames

        Parameters
        ----------
        frames: array_like (n_frames, height, width, 3)
            The stack of frames
        '''

        vals = [frames[:,loc[0],loc[1],None,:] for loc in self.pixels]
        vals = np.concatenate(vals, axis=1)

        self.values += [vals]

    def extract(self):
        '''
        Format the values captured into an (n_frames, n_pixels, 3) shaped array
        '''
        v = np.concatenate(self.values, axis=0)
        return v.reshape((-1, len(self.pixels), 3))


class BoxCatcher(ProcessorBase):
    '''
    This is a simple object that collect the values of a few pixels on the
    stream of frames

    Parameters
    ----------
    pixels: list of tuples
        The location of the pixels to collect in the image
    box_size: list  or tuple of two int
        The height and width of the bounding box to use for averaging
    agg: func
        The aggregation function to use on the box (default numpy.mean),
        it needs to be a ufunc with support for `keepdims` and `axis` options
    '''
    def __init__(self, pixels, box_size, agg=None, monitor=False):

        # call parent method
        ProcessorBase.__init__(self, monitor=monitor)

        # set the attributes
        self.pixels = pixels
        self.values = []
        self.box_size = box_size
        if agg is None:
            self.agg = np.mean
        else:
            self.agg = agg

        # precompute the slices for each pixel
        off_h = self.box_size[0] // 2
        off_v = self.box_size[1] // 2
        self.ranges = [
                [ slice(loc[0] - off_v, loc[0] + off_v + 1),
                  slice(loc[1] - off_h, loc[1] + off_h + 1), ]
                for loc in self.pixels ]

    def __process__(self, frames):
        '''
        Catch the values of the pixels in a stack of frames

        Parameters
        ----------
        frames: array_like (..., width, height, n_colors)
            The stack of frames
        '''

        extra_dims = frames.shape[:-3]  # in case the array has more than 3D

        vals = [ frames[...,rx,ry,:].reshape(extra_dims + (-1, frames.shape[-1])).copy()
                for rx, ry in self.ranges]

        self.values.append(vals)

    def extract(self):
        '''
        Format the values captured into an (n_pixels,...,n_colors) shaped array
        '''
        agg_val = self.agg(self.values, axis=-2)
        agg_val = agg_val.reshape((-1,) + agg_val.shape[-2:])
        return agg_val
