#!/bin/bash
# Launch: screen -dmS mcd bash /home/debian/sim/ngspice_examples/mc_driver.sh
cd ~/sim/ngspice_examples || exit 1
rm -f mc_dist_*.csv /tmp/mcd_DONE
for tb in ilc11_7 iv6 iv18 ilc11_8; do
  TUBE=$tb python3 mc_distributions.py >/tmp/mcd_$tb.log 2>&1 &
done
wait
touch /tmp/mcd_DONE
