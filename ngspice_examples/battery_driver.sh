#!/bin/bash
# Detached overnight-battery driver. Launch with:
#   setsid nohup bash battery_driver.sh </dev/null >/tmp/driver.log 2>&1 &
cd ~/sim/ngspice_examples || exit 1
rm -f overnight_battery_*.md
rm -rf /tmp/battery/*
echo "START $(date)"

# A, C, D as single processes; B split per-tube for parallelism.
python3 overnight_battery.py A >/tmp/full_A.log 2>&1 &
python3 overnight_battery.py C >/tmp/full_C.log 2>&1 &
python3 overnight_battery.py D >/tmp/full_D.log 2>&1 &
for tb in ilc11_7 iv6 iv18 ilc11_8; do
  TUBE=$tb python3 overnight_battery.py B >/tmp/full_B_$tb.log 2>&1 &
done
wait
echo "ALL DONE $(date)"
touch /tmp/battery_DONE
