#!/bin/bash

cat > /app/fmcalc.py << 'SOLUTION_EOF'
#!/usr/bin/env python3
"""
Catastrophe reinsurance financial module engine.
Reads OasisLMF-format CSV financial structure files and computes insured losses
through a hierarchical programme structure.
"""
import sys
import csv
import struct
import argparse
import os
from collections import defaultdict


def parse_args():
    parser = argparse.ArgumentParser(
        description='Financial module calculation engine'
    )
    parser.add_argument('-p', required=True,
                        help='Directory with FM input files')
    parser.add_argument('-a', type=int, default=0,
                        help='Allocation rule (0=aggregate, 1=back-alloc)')
    parser.add_argument('-n', action='store_true',
                        help='Output net loss instead of gross')
    parser.add_argument('--binary', action='store_true',
                        help='Use binary stream I/O')
    return parser.parse_args()


def read_csv_file(filepath):
    with open(filepath) as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def read_csv_input():
    reader = csv.DictReader(sys.stdin)
    events = defaultdict(lambda: defaultdict(dict))
    for row in reader:
        event_id = int(row['event_id'])
        if 'item_id' in row:
            item_id = int(row['item_id'])
        else:
            item_id = int(row['output_id'])
        sidx = int(row['sidx'])
        loss = float(row['loss'])
        events[event_id][item_id][sidx] = loss
    return events


def read_binary_input():
    data = sys.stdin.buffer.read()
    events = defaultdict(lambda: defaultdict(dict))
    if len(data) < 4:
        return events
    offset = 4  # skip stream header
    while offset + 8 <= len(data):
        event_id = struct.unpack_from('<i', data, offset)[0]
        offset += 4
        item_id = struct.unpack_from('<i', data, offset)[0]
        offset += 4
        while offset + 4 <= len(data):
            sidx = struct.unpack_from('<i', data, offset)[0]
            offset += 4
            if sidx == 0:
                break
            if offset + 8 > len(data):
                break
            loss = struct.unpack_from('<d', data, offset)[0]
            offset += 8
            events[event_id][item_id][sidx] = loss
    return events


def write_csv_output(output_rows):
    writer = csv.writer(sys.stdout)
    writer.writerow(['event_id', 'output_id', 'sidx', 'loss'])
    for row in output_rows:
        writer.writerow([row[0], row[1], row[2], f'{row[3]:.4f}'])


def write_binary_output(output_rows):
    buf = sys.stdout.buffer
    buf.write(struct.pack('<i', 1))
    groups = defaultdict(list)
    for event_id, output_id, sidx, loss in output_rows:
        groups[(event_id, output_id)].append((sidx, loss))
    for (event_id, output_id) in sorted(groups.keys()):
        buf.write(struct.pack('<ii', event_id, output_id))
        for sidx, loss in sorted(groups[(event_id, output_id)]):
            buf.write(struct.pack('<id', sidx, loss))
        buf.write(struct.pack('<i', 0))
    buf.flush()


def apply_calcrule(calcrule_id, x, profile):
    d1 = float(profile.get('deductible_1', 0))
    a1 = float(profile.get('attachment_1', 0))
    l1 = float(profile.get('limit_1', 0))
    sh1 = float(profile.get('share_1', 0))
    sh2 = float(profile.get('share_2', 0))
    sh3 = float(profile.get('share_3', 0))

    if calcrule_id == 100:
        return x

    elif calcrule_id == 1:
        loss = x - d1
        if loss < 0:
            loss = 0
        if loss > l1:
            loss = l1
        return loss

    elif calcrule_id == 2:
        loss = x - d1
        if loss < 0:
            loss = 0
        if loss > (a1 + l1):
            loss = l1
        else:
            loss = loss - a1
        if loss < 0:
            loss = 0
        loss = loss * sh1
        return loss

    elif calcrule_id == 3:
        if x <= d1:
            return 0
        elif x <= l1:
            return x
        else:
            return l1

    elif calcrule_id == 5:
        loss = x - x * d1
        lim = x * l1
        if loss > lim:
            loss = lim
        return loss

    elif calcrule_id == 12:
        loss = x - d1
        if loss < 0:
            loss = 0
        return loss

    elif calcrule_id == 14:
        if x <= l1:
            return x
        return l1

    elif calcrule_id == 16:
        return x * (1 - d1)

    elif calcrule_id == 20:
        if x > d1:
            return 0
        return x

    elif calcrule_id == 22:
        if sh1 == 0:
            return 0
        pre_share_limit = l1 / sh1
        all_share = sh1 * sh2 * sh3
        maxi = l1 * sh2 * sh3
        if x <= pre_share_limit:
            return x * all_share
        else:
            return maxi

    elif calcrule_id == 24:
        if sh1 == 0:
            return 0
        pre_att = a1 / sh1
        pre_att_lim = (l1 + a1) / sh1
        att_share = a1 * sh2 * sh3
        all_share = sh1 * sh2 * sh3
        maxi = l1 * sh2 * sh3
        if x <= pre_att:
            return 0
        elif x <= pre_att_lim:
            return x * all_share - att_share
        else:
            return maxi

    elif calcrule_id == 25:
        return x * sh1 * sh2 * sh3

    else:
        raise ValueError(f"Unknown calcrule_id: {calcrule_id}")


def main():
    args = parse_args()
    input_dir = args.p
    alloc_rule = args.a
    net_loss_flag = args.n
    binary_mode = args.binary

    # Read financial structure files
    programme = read_csv_file(os.path.join(input_dir, 'fm_programme.csv'))
    profile_rows = read_csv_file(os.path.join(input_dir, 'fm_profile.csv'))
    policytc = read_csv_file(os.path.join(input_dir, 'fm_policytc.csv'))
    xref = read_csv_file(os.path.join(input_dir, 'fm_xref.csv'))

    # Build profile lookup: policytc_id -> profile dict
    profiles = {}
    for row in profile_rows:
        ptc_id = int(row['policytc_id'])
        profiles[ptc_id] = row

    # Build programme hierarchy: {level_id: {to_agg_id: [from_agg_id, ...]}}
    prog_hierarchy = defaultdict(lambda: defaultdict(list))
    for row in programme:
        level = int(row['level_id'])
        from_agg = int(row['from_agg_id'])
        to_agg = int(row['to_agg_id'])
        prog_hierarchy[level][to_agg].append(from_agg)

    levels = sorted(prog_hierarchy.keys())

    # Build policytc lookup: (level_id, agg_id) -> [(layer_id, policytc_id)]
    ptc_lookup = defaultdict(list)
    for row in policytc:
        level = int(row['level_id'])
        agg = int(row['agg_id'])
        layer = int(row['layer_id'])
        ptc_id = int(row['policytc_id'])
        ptc_lookup[(level, agg)].append((layer, ptc_id))
    for key in ptc_lookup:
        ptc_lookup[key].sort()

    # Build xref lookup: (agg_id, layer_id) -> output_id
    xref_lookup = {}
    for row in xref:
        output_id = int(row['output_id'])
        agg = int(row['agg_id'])
        layer = int(row['layer_id'])
        xref_lookup[(agg, layer)] = output_id

    # Read input losses
    if binary_mode:
        events = read_binary_input()
    else:
        events = read_csv_input()

    all_output_rows = []

    for event_id in sorted(events.keys()):
        item_losses = events[event_id]

        # Store ground-up losses for back-allocation
        gul = {item_id: dict(sidx_losses)
               for item_id, sidx_losses in item_losses.items()}

        # Current losses indexed by (agg_id, layer_id) -> {sidx: loss}
        current_losses = {}
        for item_id, sidx_losses in item_losses.items():
            current_losses[(item_id, 1)] = dict(sidx_losses)

        # Store aggregated input loss at each level for net loss
        level_input_losses = {}

        for level in levels:
            groups = prog_hierarchy[level]
            new_losses = {}

            for to_agg, from_aggs in groups.items():
                layers = ptc_lookup.get((level, to_agg), [(1, None)])

                for layer_id, ptc_id in layers:
                    # Aggregate children losses for this layer
                    agg_loss = defaultdict(float)
                    for from_agg in from_aggs:
                        child_losses = current_losses.get(
                            (from_agg, layer_id))
                        if child_losses is None:
                            child_losses = current_losses.get(
                                (from_agg, 1), {}
                            )
                        for sidx, loss in child_losses.items():
                            agg_loss[sidx] += loss

                    # Save aggregated input for net loss
                    if net_loss_flag:
                        level_input_losses[
                            (to_agg, layer_id)] = dict(agg_loss)

                    # Apply calcrule
                    if ptc_id is not None:
                        profile = profiles[ptc_id]
                        calcrule = int(profile['calcrule_id'])
                        result_loss = {}
                        for sidx, loss in agg_loss.items():
                            result_loss[sidx] = apply_calcrule(
                                calcrule, loss, profile
                            )
                        new_losses[(to_agg, layer_id)] = result_loss
                    else:
                        new_losses[(to_agg, layer_id)] = dict(agg_loss)

            current_losses = new_losses

        # Generate output
        if alloc_rule == 0:
            for (agg_id, layer_id), sidx_losses in current_losses.items():
                output_id = xref_lookup.get((agg_id, layer_id))
                if output_id is None:
                    continue
                for sidx, loss in sidx_losses.items():
                    if net_loss_flag:
                        input_loss = level_input_losses.get(
                            (agg_id, layer_id), {}
                        ).get(sidx, 0)
                        loss = max(0, input_loss - loss)
                    all_output_rows.append(
                        (event_id, output_id, sidx, loss))

        elif alloc_rule == 1:
            item_to_agg = {}
            for item_id in gul:
                item_to_agg[item_id] = item_id
            for level in levels:
                from_to = {}
                for to_agg, from_aggs in prog_hierarchy[level].items():
                    for from_agg in from_aggs:
                        from_to[from_agg] = to_agg
                for item_id in item_to_agg:
                    current_agg = item_to_agg[item_id]
                    if current_agg in from_to:
                        item_to_agg[item_id] = from_to[current_agg]

            final_agg_items = defaultdict(list)
            for item_id, final_agg in item_to_agg.items():
                final_agg_items[final_agg].append(item_id)

            for (agg_id, layer_id), sidx_losses in current_losses.items():
                items_in_group = final_agg_items.get(agg_id, [])
                for sidx, total_loss in sidx_losses.items():
                    total_gul = sum(
                        gul.get(iid, {}).get(sidx, 0)
                        for iid in items_in_group
                    )
                    for item_id in items_in_group:
                        output_id = xref_lookup.get((item_id, layer_id))
                        if output_id is None:
                            continue
                        item_gul = gul.get(
                            item_id, {}).get(sidx, 0)
                        if total_gul > 0:
                            allocated = total_loss * (
                                item_gul / total_gul)
                        else:
                            allocated = 0
                        if net_loss_flag:
                            allocated = max(0, item_gul - allocated)
                        all_output_rows.append(
                            (event_id, output_id, sidx, allocated)
                        )

    all_output_rows.sort(key=lambda r: (r[0], r[1], r[2]))

    if binary_mode:
        write_binary_output(all_output_rows)
    else:
        write_csv_output(all_output_rows)


if __name__ == '__main__':
    main()
SOLUTION_EOF

cp /solution/fmtobin.py /app/fmtobin.py
cp /solution/fmtocsv.py /app/fmtocsv.py
cp /solution/run_pipeline.sh /app/run_pipeline.sh
chmod +x /app/fmcalc.py /app/fmtobin.py /app/fmtocsv.py /app/run_pipeline.sh
