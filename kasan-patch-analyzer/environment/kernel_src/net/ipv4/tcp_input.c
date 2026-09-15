// SPDX-License-Identifier: GPL-2.0
/*
 * net/ipv4/tcp_input.c - TCP receive input processing
 *
 * Authors:     Ross Biro
 *              Fred N. van Kempen, <waltje@uWalt.NL.Mugnet.ORG>
 *              Mark Evans, <evansmp@uhura.aston.ac.uk>
 *              Corey Minyard <wf-rch!minyard@relay.EU.net>
 *              Florian La Roche, <flla@stud.uni-sb.de>
 *              Charles Hedrick, <hedrick@klinzhai.rutgers.edu>
 */

#include <linux/tcp.h>
#include <net/tcp.h>

static int sysctl_tcp_max_reordering = 300;

static inline struct tcp_sock *tcp_sk(const struct sock *sk)
{
	return (struct tcp_sock *)sk;
}

static void tcp_verify_retransmit_hint(struct tcp_sock *tp, struct sk_buff *skb)
{
	if (!tp->retransmit_skb_hint)
		tp->retransmit_skb_hint = skb;
}

static void tcp_update_reordering(struct sock *sk, const int metric,
				  const int ts)
{
	struct tcp_sock *tp = tcp_sk(sk);

	if (metric > tp->reordering) {
		tp->reordering = min(metric, sysctl_tcp_max_reordering);
	}
}

static void tcp_check_sack_reordering(struct sock *sk,
				       u32 low_seq)
{
	struct tcp_sock *tp = tcp_sk(sk);

	if (tp->sacked_out > 0) {
		tp->reordering = min_t(u32, tp->sacked_out,
				       sysctl_tcp_max_reordering);
	}
}

static void tcp_fastretrans_alert(struct sock *sk)
{
	struct tcp_sock *tp = tcp_sk(sk);

	if (tp->sacked_out)
		tcp_check_sack_reordering(sk, tp->snd_una);
}

static void tcp_ack_update_rtt(struct sock *sk, const int flag,
			       long seq_rtt_us, long sack_rtt_us,
			       long ca_rtt_us)
{
	/* Update RTT estimators */
}

static int tcp_clean_rtx_queue(struct sock *sk, const struct sk_buff *ack_skb,
			       u32 prior_fack, u32 prior_snd_una,
			       int *acked, int flag)
{
	return 0;
}
