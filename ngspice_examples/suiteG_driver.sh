#!/bin/bash
# Launch: screen -dmS suiteG bash /home/debian/sim/ngspice_examples/suiteG_driver.sh
cd ~/sim/ngspice_examples || exit 1
rm -f overnight_battery_G*.md
rm -rf /tmp/suiteG/*
rm -f /tmp/suiteG_DONE
echo "START $(date)"
for tb in ilc11_7 iv6 iv18 ilc11_8; do
  TUBE=$tb python3 battery_suiteG.py >/tmp/G_$tb.log 2>&1 &
done
wait
echo "ALL DONE $(date)"
touch /tmp/suiteG_DONE
