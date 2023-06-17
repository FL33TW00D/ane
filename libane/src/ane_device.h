// SPDX-License-Identifier: MIT
/* Copyright 2022 Eileen Yoon <eyn@gmx.com> */

#ifndef __ANE_DEVICE_H__
#define __ANE_DEVICE_H__

#include "ane_dev.h"

int ane_device_open(int dev_id);
void ane_device_close(int fd);

#endif /* __ANE_DEVICE_H__ */
