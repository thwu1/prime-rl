import json, glob, os, re
RUNS = [
    ('h200 (8269569 old-infra)', '/checkpoint/ram/tianhaowu/vmvm_tb_multinode',    '/checkpoint/ram/tianhaowu/mn_eval_driver.log'),
    ('h200-v2 (8272804 LATEST)', '/checkpoint/ram/tianhaowu/vmvm_tb_multinode_v2', '/checkpoint/ram/tianhaowu/mn_eval_v2_driver.log'),
    ('h100x4-v2 (8273175 LATEST)', '/checkpoint/ram/tianhaowu/vmvm_tb_multinode_h100_4n', '/checkpoint/ram/tianhaowu/mn_eval_h100_4n_driver.log'),
    ('h100x8 (old)', '/checkpoint/ram/tianhaowu/vmvm_tb_multinode_h100', '/checkpoint/ram/tianhaowu/mn_eval_h100_driver.log'),
]
def classify(m):
    m=(m or '').lower()
    if 'sshd not ready' in m: return 'sshd_not_ready'
    if 'kex_exchange' in m or 'connection reset' in m or 'podman pull' in m: return 'ssh_reset/pull'
    if 'tunnel' in m: return 'tunnel'
    if 'reward' in m or 'test' in m: return 'grading'
    return 'other'
for label, base, drv in RUNS:
    rj=sorted(glob.glob(os.path.join(base,'**','results.jsonl'),recursive=True),key=os.path.getmtime)
    print('=== %s ==='%label)
    if rj:
        rows=[json.loads(l) for l in open(rj[-1]) if l.strip()]
        n=len(rows); ee=[r for r in rows if r.get('tb_outcome')=='env_error']
        startup=sum(1 for r in ee if (r.get('num_turns') or 0)==0)
        causes={}
        for r in ee:
            c=r.get('tb_error_class') or classify(r.get('tb_message')); causes[c]=causes.get(c,0)+1
        print('  rollouts=%d env_error=%d (%.1f%%) [startup=%d after_run=%d]'%(n,len(ee),100*len(ee)/max(n,1),startup,len(ee)-startup))
        print('  causes:',causes)
    else:
        print('  no results yet')
    if os.path.exists(drv):
        t=open(drv,errors='replace').read()
        print('  driver-log: bring-up-retries=%d sshd-not-ready=%d final-setup-fails=%d'%(
            len(re.findall(r'bring-up failed .attempt',t)), len(re.findall(r'sshd not ready',t)),
            len(re.findall(r'setup_state failed|SETUP infra-error',t))))
        print('  grade-retry: conn-lost-recovered=%d box-gone-giveup=%d grade-infra-errors=%d'%(
            len(re.findall(r'restart_session.same box. ok=True',t)),
            len(re.findall(r'box gone, giving up',t)),
            len(re.findall(r'GRADE infra-error',t))))
        mr = re.findall(r'MID-ROLLOUT conn-lost.*ok=(True|False)', t)
        print('  mid-rollout: drops=%d reconnected=%d box-gone=%d'%(
            len(mr), mr.count('True'), mr.count('False')))
