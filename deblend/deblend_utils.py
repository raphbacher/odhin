# -*- coding: utf-8 -*-
"""
Created on Thu Jun 30 10:53:50 2016

@author: raphael.bacher@gipsa-lab.fr
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import scipy.signal as ssl
from numpy import ma
from scipy.ndimage.filters import convolve
import scipy.optimize as so
from scipy.interpolate import interp1d
import astropy.units as units
import astropy.io.fits as pyfits
import math
from scipy import ndimage

import matplotlib.pyplot as plt

def block_sum(ar, fact):
    """
    Subsample a matrix *ar* by a integer factor *fact* using sums.
    """
    sx, sy = ar.shape
    X, Y = np.ogrid[0:sx, 0:sy]
    regions = sy//fact[1] * (X//fact[0]) + Y//fact[1]
    res = ndimage.sum(ar, labels=regions, index=np.arange(regions.max() + 1))
    res.shape = (sx//fact[0], sy//fact[1])
    return res


def generatePSF_HST(alphaHST, betaHST, shape=(375, 375), shapeMUSE=(25, 25)):
    """Generate PSF HST at MUSE resolution with Moffat model.
    To increase precision (as this PSF is sharp) the construction is made on a larger array
    then subsampled.
    """
    PSF_HST_HR = generateMoffatIm(shape=shape, center=(shape[0]//2, shape[1]//2),
                                      alpha=alphaHST, beta=betaHST, dim=None)
    factor = (shape[0]//shapeMUSE[0], shape[1]//shapeMUSE[1])
    PSF_HST = block_sum(PSF_HST_HR, (factor[0], factor[1]))
    PSF_HST[PSF_HST < 0.001] = 0
    PSF_HST = PSF_HST/np.sum(PSF_HST)
    return PSF_HST

def getMainSupport(u, alpha=0.999):
    """
    Get mask containing fraction alpha of total map intensity.
    """
    mask = np.zeros_like(u).astype(bool)
    for i,row in enumerate(u):
        s=np.cumsum(np.sort(row)[::-1])
        keepNumber=np.sum(s<alpha*s[-1])
        mask[i,np.argsort(row,axis=None)[-keepNumber:]]=True
    return mask


def apply_resampling_window(im):

    """Multiply the FFT of an image with the blackman anti-aliasing window
    that would be used by default by the MPDAF Image.resample()
    function for the specified image grid.
    Parameters
    ----------
    im  : numpy.ndarray
       The resampled image.
    """

    # Create an array which, for each pixel in the FFT image, holds
    # the radial spatial-frequency of the pixel center, divided by the
    # Nyquist folding frequency (ie. 0.5 cycles/image_pixel).
    shape = im.shape
    imfft = np.fft.rfft2(im)
    f = np.sqrt((np.fft.rfftfreq(shape[1]) / 0.5)**2 +
                (np.fft.fftfreq(shape[0]) / 0.5)[np.newaxis,:].T**2)

    # Scale the FFT by the window function, calculating the blackman
    # window function as a function of frequency divided by its cutoff
    # frequency.

    imfft *= np.where(f <= 1.0, 0.42 + 0.5 * np.cos(np.pi * f) + 0.08 * np.cos(2*np.pi * f), 0.0)
    return np.fft.irfft2(imfft,shape)

def convertFilt(filt,wave=None,x=None):
    """
    Resample response of HST filter on the spectral grid of MUSE

    filt: 2d array (wavelength,amplitude) of response filter
    wave: mpdaf wave object
    """
    if wave is not None:
        x = wave.coord()
    f=interp1d(filt[:,0],filt[:,1],fill_value=0,bounds_error=False)
    return np.array(f(x))


def calcFSF(a, b, beta, listLambda, center=(12, 12), shape=(25, 25), dim='MUSE'):
    """
    Build list of FSF images (np arrays) from parameters a,b and beta.
    fwhm=a+b*lmbda, and beta is the Moffat parameter.
    """
    listFSF = []
    for lmbda in listLambda:
        fwhm = a+b*lmbda

        alpha = np.sqrt(fwhm**2/(4*(2**(1/beta)-1)))
        listFSF.append(generateMoffatIm(center, shape, alpha, beta, dim=dim))
    return listFSF


def Moffat(r, alpha, beta):
    """
    Compute Moffat values for array of distances *r* and Moffat parameters *alpha* and *beta*
    """
    return (beta-1)/(math.pi*alpha**2)*(1+(r/alpha)**2)**(-beta)

def generateMoffatIm(center=(12,12),shape=(25,25),alpha=2,beta=2.5,dx=0.,dy=0.,dim='MUSE'):
    """
    By default alpha is supposed to be given in arsec, if not it is given in MUSE pixel.
    a,b allow to decenter slightly the Moffat image.
    """
    ind = np.indices(shape)
    r = np.sqrt(((ind[0]-center[0]+dx)**2 + ((ind[1]-center[1]+dy))**2))
    if dim == 'MUSE':
        r = r*0.2
    elif dim == 'HST':
        r = r*0.03
    res = Moffat(r, alpha, beta)
    res = res/np.sum(res)
    return res


def normalize(a, axis=-1, order=2, returnCoeff=False):
    """
    normalize array along axis
    """
    l2 = np.atleast_1d(np.linalg.norm(a, order, axis))
    l2[l2 == 0] = 1
    if returnCoeff is True:
        return a / np.expand_dims(l2, axis), np.expand_dims(l2, axis)
    else:
        return a / np.expand_dims(l2, axis)





def convertIntensityMap(intensityMap,muse,hst,fwhm,beta,antialias=False,psf_hst=True):
    """
    Parameters
    ----------
    intensityMap : `ndarray`
        The matrix of intensity maps (one row per object) at HST resolution

    hst : `mpdaf.obj.Image`
       The HST image to be resampled.
    muse : `mpdaf.obj.Image` of `mpdaf.obj.Cube`
       The MUSE image or cube to use as the template for the HST image.
    fwhm : `float`
        fwhm of MUSE FSF
    beta : `float`
        Moffat beta parameter of MUSE FSF
    antialias : `bool`
        Use antialising filter or not.
        Default to False (because a broad convolution is applied afterwards)
    psf_hst : `bool`
        Use HST-MUSE transfert function instead of MUSE FSF. Default to True


    Returns
    -------
    intensityMapMuse : `ndarray`
       The matrix of intensity maps (one row per object) at MUSE resolution
       (and convolved by MUSE FSF or HST-MUSE transfert function)
    """
    intensityMapMuse = np.zeros((intensityMap.shape[0], muse.data.size))
    hst_ref = hst.copy()


    if psf_hst == True: #get HST-MUSE transfert function
        tmp_dir='./tmp/'
        imPSFMUSE = pyfits.open(tmp_dir+'kernel_%s.fits'%fwhm)[1].data
        imPSFMUSE=imPSFMUSE/np.sum(imPSFMUSE)
    else:
        alpha= fwhm / 2.0 / np.sqrt((2.0**(1.0 / beta) - 1.0))
        imPSFMUSE = generateMoffatIm(center=(50,50),shape=(101,101),alpha=alpha,beta=beta,dim='HST')
    for i in range(intensityMap.shape[0]):
        hst_ref.data = intensityMap[i].reshape(hst_ref.shape)


        hst_ref.data = ssl.fftconvolve(hst_ref.data,imPSFMUSE,mode='same')
        hst_ref_muse = regrid_hst_like_muse(hst_ref, muse, inplace=False,
                                            antialias=antialias)

        hst_ref_muse = rescale_hst_like_muse(hst_ref_muse, muse, inplace=False)
        hst_ref_muse.mask[:] = False

        intensityMapMuse[i] = hst_ref_muse.data.flatten()
    return intensityMapMuse



### functions taken from muse_analysis and slighlty modified


def regrid_hst_like_muse(hst, muse, inplace=True, antialias=True):
    """
    Resample an HST image onto the spatial coordinate grid of a given
    MUSE image or MUSE cube.

    Parameters
    ----------
    hst : `mpdaf.obj.Image`
       The HST image to be resampled.
    muse : `mpdaf.obj.Image` of `mpdaf.obj.Cube`
       The MUSE image or cube to use as the template for the HST image.
    inplace : bool
       (This defaults to True, because HST images tend to be large)
       If True, replace the contents of the input HST image object
       with the resampled image.
       If False, return a new Image object that contains the resampled
       image.

    Returns
    -------
    out : `mpdaf.obj.Image`
       The resampled HST image.

    """

    # Operate on a copy of the input image?

    if not inplace:
        hst = hst.copy()

    # If a MUSE cube was provided, extract a single-plane image to use
    # as the template.

    if muse.ndim > 2:
        muse = muse[0,:,:]

    # Mask the zero-valued blank margins of the HST image.

    ########"
    #Removed here because we work on intensity maps with lot of zeros
    #np.ma.masked_inside(hst.data, -1e-10, 1e-10, copy=False)
    #########

    # Resample the HST image onto the same coordinate grid as the MUSE
    # image.

    return hst.align_with_image(muse, cutoff=0.0, flux=True, inplace=True,antialias=antialias)

class HstFilterInfo(object):
    """An object that contains the filter characteristics of an HST
    image.

    Parameters
    ----------
    hst : `mpdaf.obj.Image` or str
       The HST image to be characterized, or the name of an HST filter,
       such as "F606W.

    Attributes
    ----------
    filter_name : str
       The name of the filter.
    abmag_zero : float
       The AB magnitude that corresponds to the zero electrons/s\n
       from the camera (see ``https://archive.stsci.edu/prepds/xdf``).
    photflam : float
       The calibration factor to convert pixel values in\n
       electrons/s to erg cm-2 s-1 Angstrom-1.\n
       Calculated using::

         photflam = 10**(-abmag_zero/2.5 - 2*log10(photplam) - 0.9632)

       which is a rearranged form of the following equation from\n
       ``http://www.stsci.edu/hst/acs/analysis/zeropoints``::

         abmag_zero = -2.5 log10(photflam)-5 log10(photplam)-2.408

    photplam : float
       The pivot wavelength of the filter (Angstrom)\n
       (from ``http://www.stsci.edu/hst/acs/analysis/bandwidths``)
    photbw : float
       The effective bandwidth of the filter (Angstrom)\n
       (from ``http://www.stsci.edu/hst/acs/analysis/bandwidths``)

    """

    # Create a class-level dictionary of HST filter characteristics.
    # See the documentation of the attributes for the source of these
    # numbers.

    _filters = {
        "F606W" :  {"abmag_zero" : 26.51,    "photplam"  : 5921.1,
                    "photflam"   : 7.73e-20, "photbw"    : 672.3},
        "F775W" :  {"abmag_zero" : 25.69,    "photplam"  : 7692.4,
                    "photflam"   : 9.74e-20, "photbw"    : 434.4},
        "F814W" :  {"abmag_zero" : 25.94,    "photplam"  : 8057.0,
                    "photflam"   : 7.05e-20, "photbw"    : 652.0},
        "F850LP" : {"abmag_zero" : 24.87,    "photplam"  : 9033.1,
                    "photflam"   : 1.50e-19, "photbw"    : 525.7}
    }

    def __init__(self, hst):

        # If an image has been given, get the name of the HST filter
        # from the FITS header of the HST image, and convert the name
        # to upper case. Otherwise get it from the specified filter
        # name.

        if isinstance(hst, str):
            self.filter_name = hst.upper()
        elif "FILTER" in hst.primary_header:
            self.filter_name = hst.primary_header['FILTER'].upper()
        elif ("FILTER1" in hst.primary_header and
              hst.primary_header['FILTER1'] != 'CLEAR1L'):
            self.filter_name = hst.primary_header['FILTER1'].upper()
        elif ("FILTER2" in hst.primary_header and
              hst.primary_header['FILTER2'] != 'CLEAR2L'):
            self.filter_name = hst.primary_header['FILTER2'].upper()


        # Get the dictionary of the characteristics of the filter.

        if self.filter_name in self.__class__._filters:
            info = self.__class__._filters[self.filter_name]


        # Record the characteristics of the filer.

        self.abmag_zero = info['abmag_zero']
        self.photflam = info['photflam']
        self.photplam = info['photplam']
        self.photbw = info['photbw']

def rescale_hst_like_muse(hst, muse, inplace=True):
    """Rescale an HST image to have the same flux units as a given MUSE image.

    Parameters
    ----------
    hst : `mpdaf.obj.Image`
       The HST image to be resampled.
    muse : `mpdaf.obj.Image` or `mpdaf.obj.Cube`
       A MUSE image or cube with the target flux units.
    inplace : bool
       (This defaults to True, because HST images tend to be large)
       If True, replace the contents of the input HST image object
       with the rescaled image.
       If False, return a new Image object that contains the rescaled
       image.

    Returns
    -------
    out : `mpdaf.obj.Image`
       The rescaled HST image.

    """

    # Operate on a copy of the input image?

    if not inplace:
        hst = hst.copy()

    # Get the characteristics of the HST filter.

    filt = HstFilterInfo(hst)

    # Calculate the calibration factor needed to convert from
    # electrons/s in the HST image to MUSE flux-density units.

    cal = filt.photflam * units.Unit("erg cm-2 s-1 Angstrom-1").to(muse.unit)

    # Rescale the HST image to have the same units as the MUSE image.

    hst.data *= cal
    if hst.var is not None:
        hst.var *= cal**2
    hst.unit = muse.unit

    return hst
