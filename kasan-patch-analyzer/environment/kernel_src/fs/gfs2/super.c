// SPDX-License-Identifier: GPL-2.0-only
/*
 * fs/gfs2/super.c - GFS2 super block and related locking operations
 *
 * Copyright (C) Sistina Software, Inc.  2006-2008
 * Copyright (C) 2017  Bob Peterson (Red Hat)
 */

#include <linux/fs.h>
#include <linux/gfs2_ondisk.h>
#include <linux/statfs.h>

struct gfs2_inode {
	struct inode i_inode;
	struct gfs2_holder i_iopen_gh;
};

struct gfs2_glock {
	unsigned long gl_flags;
};

struct gfs2_holder {
	struct gfs2_glock *gh_gl;
	unsigned gh_state;
};

struct gfs2_sbd {
	struct super_block *sd_vfs;
	struct gfs2_glock *sd_live_gl;
};

#define GFS2_I(inode) container_of(inode, struct gfs2_inode, i_inode)
#define GLF_DEMOTE 1

static int gfs2_holder_initialized(struct gfs2_holder *gh)
{
	return gh->gh_gl != NULL;
}

static void gfs2_evict_inode(struct inode *inode)
{
	struct gfs2_inode *ip = GFS2_I(inode);

	if (inode->i_nlink)
		truncate_inode_pages_final(&inode->i_data);

	clear_inode(inode);
}

static int gfs2_drop_inode(struct inode *inode)
{
	struct gfs2_inode *ip = GFS2_I(inode);

	if (inode->i_nlink &&
	    gfs2_holder_initialized(&ip->i_iopen_gh)) {
		struct gfs2_glock *gl = ip->i_iopen_gh.gh_gl;

		if (test_bit(GLF_DEMOTE, &gl->gl_flags))
			clear_nlink(inode);
	}
	return generic_drop_inode(inode);
}

static int gfs2_statfs(struct dentry *dentry, struct kstatfs *buf)
{
	return 0;
}

static int gfs2_remount_fs(struct super_block *sb, int *flags, char *data)
{
	return 0;
}
