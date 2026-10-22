"""Read-only context snapshots outside measured calls; no host policy changes."""
import json
import os
from pathlib import Path
import time


def read_optional(path):
    try:return Path(path).read_text().strip()
    except (FileNotFoundError,PermissionError,OSError):return None


def snapshot():
    affinity=sorted(os.sched_getaffinity(0))
    stats=read_optional('/proc/stat') or ''
    counters={}
    for line in stats.splitlines():
        fields=line.split()
        if fields and fields[0] in ['cpu',*[f'cpu{cpu}' for cpu in affinity]]:
            counters[fields[0]]=[int(value) for value in fields[1:]]
    wanted={'MemAvailable','HugePages_Total','HugePages_Free','HugePages_Rsvd','Hugepagesize'}
    memory={}
    for line in (read_optional('/proc/meminfo') or '').splitlines():
        name,_,value=line.partition(':')
        if name in wanted:memory[name]=value.strip()
    return dict(monotonic_ns=time.monotonic_ns(),wall_time_ns=time.time_ns(),
        host=os.uname().nodename,kernel=os.uname().release,affinity=affinity,
        loadavg=read_optional('/proc/loadavg'),memory=memory,cpu_jiffies=counters,
        cpu_policy={str(cpu):{name:read_optional(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/{name}')
                             for name in ('scaling_governor','scaling_cur_freq')}
                    for cpu in affinity},
        pcie={name:read_optional('/sys/bus/pci/devices/'+os.environ.get('COYOTE_BENCH_PCI_BDF','0000:c4:00.0')+'/'+name)
              for name in ('current_link_width','current_link_speed')},
        gpu={str(p):read_optional(p) for pattern in ('gpu_busy_percent','mem_info_vram_used','pp_dpm_sclk','hwmon/hwmon*/temp*_input')
             for p in Path('/sys/bus/pci/devices/0000:03:00.0').glob(pattern)})


def record(output,case_id,position):
    output.write(json.dumps(dict(case_id=case_id,position=position,**snapshot()))+'\n')
    output.flush()
