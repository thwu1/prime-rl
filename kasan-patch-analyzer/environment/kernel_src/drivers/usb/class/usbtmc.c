// SPDX-License-Identifier: GPL-2.0+
/*
 * drivers/usb/class/usbtmc.c - USB Test & Measurement class driver
 *
 * Copyright (C) 2007 Stefan Kopp, Gechingen, Germany
 * Copyright (C) 2008 Novell, Inc.
 * Copyright (C) 2008 Greg Kroah-Hartman <gregkh@suse.de>
 * Copyright (C) 2018 IVI Foundation, Inc.
 */

#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/kref.h>
#include <linux/slab.h>
#include <linux/poll.h>
#include <linux/mutex.h>
#include <linux/usb.h>
#include <linux/compat.h>
#include <linux/usb/tmc.h>

struct usbtmc_device_data {
	struct usb_interface *intf;
	struct usb_device *usb_dev;
	unsigned int bulk_in;
	unsigned int bulk_out;
	u8 bTag;
	u8 bTag_last_write;
	u8 bTag_last_read;
	unsigned char *iin_buffer;
	unsigned char iin_bTag;
	unsigned char bNotify1;
	unsigned char bNotify2;
	int iin_ep_present;
	int timeout;
	struct mutex io_mutex;
	wait_queue_head_t waitq;
	int iin_flag;
	int term_char_enabled;
	int auto_abort;
	struct kref kref;
};

static void usbtmc_delete(struct kref *kref)
{
	struct usbtmc_device_data *data = container_of(kref,
		struct usbtmc_device_data, kref);

	usb_put_dev(data->usb_dev);
	kfree(data);
}

static int usbtmc_open(struct inode *inode, struct file *filp)
{
	return 0;
}

static int usbtmc_release(struct inode *inode, struct file *filp)
{
	return 0;
}

static ssize_t usbtmc_read(struct file *filp, char __user *buf,
			    size_t count, loff_t *f_pos)
{
	return 0;
}

static ssize_t usbtmc_write(struct file *filp, const char __user *buf,
			     size_t count, loff_t *f_pos)
{
	return count;
}

static void usbtmc_interrupt(struct urb *urb)
{
	struct usbtmc_device_data *data = urb->context;
	int status = urb->status;

	switch (status) {
	case 0: /* SUCCESS */
		/* check the length of the interrupt data */
		/* Decode interrupt-IN notification per USBTMC-USB488 4.3.1 */
		if (data->iin_buffer[0] == 1) {
			/* check Tag */
			if (data->iin_buffer[1] == data->iin_bTag) {
				data->bNotify1 = data->iin_buffer[2];
				data->bNotify2 = data->iin_buffer[3];
			}
		}
		break;
	case -EOVERFLOW:
		dev_err(&data->intf->dev, "%s: overflow\n", __func__);
		break;
	case -ECONNRESET:
	case -ENOENT:
	case -ESHUTDOWN:
	case -EILSEQ:
	case -ETIME:
	case -EPIPE:
		/* urb terminated, clean up */
		dev_dbg(&data->intf->dev, "%s: urb terminated, status: %d\n",
			__func__, status);
		return;
	default:
		dev_err(&data->intf->dev, "%s: unknown status %d\n",
			__func__, status);
		break;
	}

exit:
	status = usb_submit_urb(urb, GFP_ATOMIC);
	if (status)
		dev_err(&data->intf->dev, "%s: resubmit urb failed, %d\n",
			__func__, status);
}

static int usbtmc_probe(struct usb_interface *intf,
			const struct usb_device_id *id)
{
	struct usbtmc_device_data *data;

	data = kzalloc(sizeof(*data), GFP_KERNEL);
	if (!data)
		return -ENOMEM;

	data->intf = intf;
	data->usb_dev = usb_get_dev(interface_to_usbdev(intf));
	kref_init(&data->kref);
	mutex_init(&data->io_mutex);
	init_waitqueue_head(&data->waitq);

	usb_set_intfdata(intf, data);

	return 0;
}

static void usbtmc_disconnect(struct usb_interface *intf)
{
	struct usbtmc_device_data *data = usb_get_intfdata(intf);

	usb_set_intfdata(intf, NULL);
	kref_put(&data->kref, usbtmc_delete);
}
