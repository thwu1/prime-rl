"""Create Zarr stores for the rechunking evaluation task.

"""
import zarr

stores_dir = '/app/zarr_stores'

zarr.open(f'{stores_dir}/grid_2d', mode='w',
          shape=(100, 200), chunks=(100, 10), dtype='float64')

zarr.open(f'{stores_dir}/spectral', mode='w',
          shape=(500, 500), chunks=(500, 5), dtype='float64')

zarr.open(f'{stores_dir}/climate_3d', mode='w',
          shape=(365, 180, 360), chunks=(1, 180, 360), dtype='float32')

zarr.open(f'{stores_dir}/pressure_1d', mode='w',
          shape=(10000,), chunks=(50,), dtype='float32')

zarr.open(f'{stores_dir}/velocity_2d', mode='w',
          shape=(200, 300), chunks=(20, 300), dtype='float64')

print(f"Created 5 Zarr stores in {stores_dir}")
