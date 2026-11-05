"""As correntes partem dos pontos âmbar da própria imagem, sem refazer o terreno."""
import numpy as np
from therion.interface.scene_flow import terrain_routes


def test_routes_are_deterministic_finite_and_stay_in_the_lit_foreground():
    pixels=np.zeros((120,240,4),dtype='uint8');pixels[72:,:,:3]=[210,100,12];pixels[:,:,3]=255
    first=terrain_routes(pixels,80);second=terrain_routes(pixels,80)
    assert first.shape==(80,8) and first.dtype==np.float32
    assert np.array_equal(first,second) and np.isfinite(first).all()
    assert (first[:,:4]>=0).all() and (first[:,:4]<=1).all()
    assert (first[:,[1,3]]<.41).all()
    assert (np.linalg.norm(first[:,:2]-first[:,2:4],axis=1)>.001).all()
    assert (first[:,5]>0).all()


def test_empty_or_unlit_image_does_not_invent_flow_paths():
    assert terrain_routes(np.zeros((80,120,4),dtype='uint8')).shape==(0,8)
    assert terrain_routes(np.zeros((1,1,4),dtype='uint8')).shape==(0,8)
