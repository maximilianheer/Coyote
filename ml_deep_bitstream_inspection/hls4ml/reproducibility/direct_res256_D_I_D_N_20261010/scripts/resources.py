import math,re
RESOURCES=("LUT","FF","BRAM_tiles","DSP","URAM")
def parse_hierarchy(text):
    if not re.search(r'Design State\s*:\s*(?:Physopt postRoute|Routed)',text):
        raise ValueError('Routed utilization report required')
    header=None;stack=[];rows={}
    for line in text.splitlines():
        cells=line.split('|')[1:-1]
        if not cells:continue
        values=[cell.strip() for cell in cells]
        if values[0]=='Instance':header=values;continue
        if header is None or len(values)!=len(header):continue
        name=values[0]
        if not name or name.startswith('('):continue  # Parent-local subtotal, not a second instance.
        data=dict(zip(header,values))
        try:
            counts=dict(LUT=int(data['Total LUTs']),FF=int(data['FFs']),
                        BRAM_tiles=int(data['RAMB36'])+int(data['RAMB18'])/2,
                        DSP=int(data['DSP Blocks']),URAM=int(data['URAM']))
        except (KeyError,ValueError) as error:
            raise ValueError('Unsupported/incomplete hierarchy row: '+name) from error
        depth=len(cells[0])-len(cells[0].lstrip())
        while stack and stack[-1][0]>=depth:stack.pop()
        path='/'.join([item[1] for item in stack]+[name])
        if path in rows:raise ValueError('Duplicate hierarchy path: '+path)
        rows[path]=counts;stack.append((depth,name))
    if not rows:raise ValueError('Empty hierarchy report')
    return rows

def parse_capacity(text):
    labels={'CLB LUTs':'LUT','CLB Registers':'FF','Block RAM Tile':'BRAM_tiles','DSPs':'DSP','URAM':'URAM'}
    header=[];capacity={};used={}
    for line in text.splitlines():
        cells=[cell.strip() for cell in line.split('|')[1:-1]]
        if not cells:continue
        if cells[0]=='Site Type':header=cells;continue
        if 'Available' not in header or len(cells)!=len(header) or cells[0] not in labels:continue
        row=dict(zip(header,cells));key=labels[cells[0]]
        value=float(row['Available']);count=float(row['Used'])
        if key in capacity and (capacity[key]!=value or used[key]!=count):
            raise ValueError('Conflicting device capacity rows')
        capacity[key]=value;used[key]=count
    if set(capacity)!=set(RESOURCES) or any(value<=0 for value in capacity.values()):
        raise ValueError('Incomplete device resource capacities')
    return capacity,used

def unique(rows,leaf,under=None,required=True):
    matches=[path for path in rows if path.rsplit('/',1)[-1]==leaf and
             (under is None or path.startswith(under+'/'))]
    if len(matches)!=1:
        if not matches and not required:return None
        raise ValueError('Expected unique hierarchy instance: '+leaf)
    return matches[0]

def attribute(hierarchy,summary,variant):
    rows=parse_hierarchy(hierarchy);capacity,total=parse_capacity(summary)
    top=next(iter(rows));wrapper=unique(rows,'inst_user_wrapper_0');app=unique(rows,'inst_user_c0_0',wrapper)
    if rows[top]!=total:raise ValueError('Hierarchy and device summary totals differ')
    components={}
    names={'preprocessing':'checker_path.preprocess','inference_and_publication':'checker_path.cnn',
           'pixel_fifo':'checker_path.pixel_fifo','control':'control'} if variant=='D_I' else {}
    if variant=='D_N':names['control']='control'
    if variant=='R_S':
        names.update(preprocessing='raw_bitstream_downsample_to_input_stream_U0',inference_and_publication='production_infer_and_publish_U0',pixel_fifo='bitstream_input_U')
    names['ILA']='inst_ila_benchmark_keepalive'
    for label,leaf in names.items():
        path=unique(rows,leaf,app)
        if any(path.startswith(value['path']+'/') or value['path'].startswith(path+'/') for value in components.values()):
            raise ValueError('Overlapping component attribution')
        components[label]=dict(path=path,resources=rows[path])
    remaining={key:rows[wrapper][key]-sum(value['resources'][key] for value in components.values()) for key in RESOURCES}
    if any(value<0 for value in remaining.values()):raise ValueError('Components exceed wrapper totals')
    outside={key:total[key]-rows[wrapper][key] for key in RESOURCES}
    if any(value<0 for value in outside.values()):raise ValueError('Wrapper exceeds device totals')
    # BRAM is allocated in half-tile units; all other limits are integral.
    limits={key:math.floor(capacity[key]*.1*(2 if key=='BRAM_tiles' else 1))/(2 if key=='BRAM_tiles' else 1)
            for key in RESOURCES}
    return dict(variant=variant,scope='routed user wrapper including Coyote interfaces and ILA; no board-latency implication',
                capacity=capacity,limits_10_percent=limits,full_design=total,wrapper_path=wrapper,
                wrapper=rows[wrapper],wrapper_percent={key:100*rows[wrapper][key]/capacity[key] for key in RESOURCES},
                meets_resource_target={key:rows[wrapper][key]<=limits[key] for key in RESOURCES},
                components=components,remaining_wrapper_and_interfaces=remaining,outside_wrapper=outside,
                attribution_note='Inclusive, non-overlapping component roots; remaining logic is a residual, not isolated physical cost')
