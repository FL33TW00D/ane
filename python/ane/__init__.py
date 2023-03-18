#!/usr/bin/python3

# SPDX-License-Identifier: MIT
# Copyright 2022 Eileen Yoon <eyn@gmx.com>

import ctypes
from ctypes import c_void_p, c_int, c_uint64, byref
from ctypes import create_string_buffer

import os
import atexit
import numpy as np
from copy import deepcopy

ANE_TILE_COUNT = 0x20
def tile_align(x): return (x + 0x4000 - 1) & -0x4000

class Driver:
	def __init__(self, path):
		self.lib = ctypes.cdll.LoadLibrary(path)
		self.lib.pyane_init.restype = c_void_p
		self.lib.pyane_free.argtypes = [c_void_p]
		self.lib.pyane_exec.argtypes = [c_void_p]
		self.lib.pyane_send.argtypes = [c_void_p] + [c_void_p] * ANE_TILE_COUNT
		self.lib.pyane_read.argtypes = [c_void_p] + [c_void_p] * ANE_TILE_COUNT
		self.lib.pyane_tile.argtypes = [c_void_p] + [c_void_p, c_void_p, c_int]
		self.lib.pyane_info.argtypes = [c_void_p] + [ctypes.POINTER(c_int)] * 2
		self.lib.pyane_nchw.argtypes = [c_void_p] + [ctypes.POINTER(c_uint64)] * 6 * ANE_TILE_COUNT * 2
		self.handles = {}
		atexit.register(self.cleanup)

	def cleanup(self):
		for handle in self.handles:
			self.lib.pyane_free(handle)

	def register(self):
		handle = self.lib.pyane_init()
		if (handle == None): raise RuntimeError("driver error")
		self.handles[handle] = handle
		return handle

class Model:
	def __init__(self, path):
		if (not os.path.dirname(path)):
			path = os.path.join(".", path)
		self.driver = Driver(path)
		self.handle = self.driver.register()

		info = [ctypes.c_int(), ctypes.c_int()]
		self.driver.lib.pyane_info(self.handle, byref(info[0]), byref(info[1]))
		self.src_count, self.dst_count = info[0].value, info[1].value

		nchw = [ctypes.c_uint64() for x in range(ANE_TILE_COUNT * 6 * 2)]
		self.driver.lib.pyane_nchw(self.handle, *[byref(nchw[n]) for n in range(len(nchw))])
		self.src_nchw = tuple([tuple(x.value for x in nchw[n*6:(n+1)*6]) for n in range(self.src_count)])
		self.dst_nchw = tuple([tuple(x.value for x in nchw[n*6:(n+1)*6]) for n in range(ANE_TILE_COUNT, ANE_TILE_COUNT + self.dst_count)])

		self.src_size = tuple([tile_align(nchw[0] * nchw[1] * nchw[4]) for nchw in self.src_nchw])
		self.dst_size = tuple([tile_align(nchw[0] * nchw[1] * nchw[4]) for nchw in self.dst_nchw])
		self.outputs = [create_string_buffer(size) for size in self.dst_size] + [b''] * (ANE_TILE_COUNT - self.dst_count)

	def predict(self, inputs):
		assert(len(inputs) == self.src_count)
		padded = inputs + [b''] * (ANE_TILE_COUNT - self.src_count)
		self.driver.lib.pyane_send(self.handle, *padded)
		self.driver.lib.pyane_exec(self.handle)
		self.driver.lib.pyane_read(self.handle, *self.outputs)
		return deepcopy(self.outputs[:self.dst_count])

	def arr2tile(self, arr, idx):
		assert((arr.dtype == np.float16) and (arr.shape == self.src_nchw[idx][:4]))
		data = arr.tobytes(order='C')
		tile = create_string_buffer(self.src_size[idx])
		self.driver.lib.pyane_tile(self.handle, data, tile, idx)
		return tile

	def tile2arr(self, tile, idx):
		N, C, H, W, P, R = self.dst_nchw[idx]
		new_N, new_C, new_H, new_W = N, C, P//R, R//2
		arr = np.frombuffer(tile, dtype=np.float16)[:new_N*new_C*new_H*new_W]
		return arr.reshape((new_N, new_C, new_H, new_W))[:N, :C, :H, :W]

	def tile(self, inarrs):  # list of numpy arrays
		return [self.arr2tile(inarrs[idx], idx) for idx in range(self.src_count)]

	def untile(self, outtiles):  # list of bytes tiles
		return [self.tile2arr(outtiles[idx], idx) for idx in range(self.dst_count)]