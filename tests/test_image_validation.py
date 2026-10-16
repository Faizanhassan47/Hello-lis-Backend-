from pathlib import Path

from PIL import Image

from image_validation import ImageValidationError, validate_image_file
from scanner_adapters import ADAPTERS


def test_calibrated_png_validation(tmp_path):
    path = tmp_path / 'calibrated.png'
    Image.new('RGB', (120, 80), 'white').save(path, dpi=(254, 254))
    result = validate_image_file(path)
    assert result['valid'] is True
    assert result['format'] == 'PNG'
    assert result['width'] == 120 and result['height'] == 80
    assert result['level_count'] == 1
    assert result['physical_calibration']['available'] is True
    assert abs(result['physical_calibration']['pixel_size_microns_x'] - 100) < 1


def test_unsupported_and_corrupt_files_are_rejected(tmp_path):
    unsupported = tmp_path / 'image.bmp'
    unsupported.write_bytes(b'BM')
    corrupt = tmp_path / 'image.png'
    corrupt.write_bytes(b'not-a-png')
    for path in (unsupported, corrupt):
        try:
            validate_image_file(path)
        except ImageValidationError:
            pass
        else:
            raise AssertionError(f'{path.name} should fail validation')


def test_wsi_pyramid_metadata_and_calibration(tmp_path):
    path = tmp_path / 'slide.svs'
    path.write_bytes(b'fake-wsi-content')

    class Region:
        def load(self):
            return None

    class Slide:
        dimensions = (10000, 8000)
        level_count = 3
        level_dimensions = ((10000, 8000), (2500, 2000), (625, 500))
        level_downsamples = (1.0, 4.0, 16.0)
        properties = {'openslide.vendor':'aperio','openslide.mpp-x':'0.25','openslide.mpp-y':'0.25','aperio.AppMag':'40'}
        def __init__(self, _path): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read_region(self, *_args): return Region()

    class OpenSlideModule:
        OpenSlide = Slide
        PROPERTY_NAME_VENDOR = 'openslide.vendor'
        PROPERTY_NAME_MPP_X = 'openslide.mpp-x'
        PROPERTY_NAME_MPP_Y = 'openslide.mpp-y'

    result = validate_image_file(path, OpenSlideModule)
    assert result['format'] == 'aperio'
    assert result['level_count'] == 3
    assert result['pyramid_levels'][2] == {'level':2,'width':625,'height':500,'downsample':16.0}
    assert result['physical_calibration']['available'] is True
    assert result['physical_calibration']['pixel_size_microns_x'] == 0.25


def test_adapter_registry_routes_supported_formats(tmp_path):
    assert ADAPTERS.for_path(tmp_path / 'slide.png').name == 'generic-raster'
    assert ADAPTERS.for_path(tmp_path / 'slide.svs').name == 'generic-openslide'
    assert {item['name'] for item in ADAPTERS.describe()} == {'generic-raster','generic-openslide'}
