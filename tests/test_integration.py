import numpy as np
from azint import AzimuthalIntegrator

poni_file = 'tests/test.poni'
pixel_size = 1.0e-4
img = np.ones((1000, 1000), dtype=np.uint16)

def save_divide(a, b):
    return np.divide(a, b, out=np.zeros_like(a), where=b!=0.0)

def test1d():
    ai = AzimuthalIntegrator(poni_file, img.shape, pixel_size, 4, 1000, solid_angle=False) 
    res, _ = ai.integrate(img)
    assert(np.allclose(res, 1.0))
    
def test2d():
    ai = AzimuthalIntegrator(poni_file, img.shape, pixel_size, 4, 1000, 360, solid_angle=False) 
    res, _, norm = ai.integrate(img, normalized=False)
    projection = save_divide(np.sum(res, axis=0), np.sum(norm, axis=0))
    assert(np.allclose(projection, 1.0))
    
def test_custom_ranges():
    q = np.array([0.0, 0.1, 0.2, 0.3, 0.4])
    phi = np.linspace(0.0, 360.0, 180)
    ai = AzimuthalIntegrator(poni_file, img.shape, pixel_size, 4, q, phi, solid_angle=False)
    assert(np.allclose(0.5*(q[1:] + q[:-1]), ai.radial_axis))
    assert(np.allclose(0.5*(phi[1:] + phi[:-1]), ai.azimuth_axis))
