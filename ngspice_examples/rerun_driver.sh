#!/bin/bash
# Re-run the full battery + supplement + Suite G on the realistic per-tube tau_th.
# Launch: screen -dmS rerun bash /home/debian/sim/ngspice_examples/rerun_driver.sh
cd ~/sim/ngspice_examples || exit 1
rm -f overnight_battery_*.md
rm -rf /tmp/battery /tmp/battery_sup /tmp/suiteG
rm -f /tmp/rerun_DONE
echo "START $(date)"
# main battery: A,C,D single procs + B per-tube
python3 overnight_battery.py A >/tmp/full_A.log 2>&1 &
python3 overnight_battery.py C >/tmp/full_C.log 2>&1 &
python3 overnight_battery.py D >/tmp/full_D.log 2>&1 &
for tb in ilc11_7 iv6 iv18 ilc11_8; do TUBE=$tb python3 overnight_battery.py B >/tmp/full_B_$tb.log 2>&1 & done
# supplement E,F
python3 battery_supplement.py >/tmp/supp.log 2>&1 &
# Suite G per-tube
for tb in ilc11_7 iv6 iv18 ilc11_8; do TUBE=$tb python3 battery_suiteG.py >/tmp/G_$tb.log 2>&1 & done
wait
echo "ALL DONE $(date)"
touch /tmp/rerun_DONE
