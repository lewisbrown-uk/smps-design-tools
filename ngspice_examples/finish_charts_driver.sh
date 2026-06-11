#!/bin/bash
# Launch: screen -dmS finish bash /home/debian/sim/ngspice_examples/finish_charts_driver.sh
cd ~/sim/ngspice_examples || exit 1
rm -f traj_iv18.csv traj_ilc11_8.csv mc_dist_*.csv /tmp/finish_DONE
echo "START $(date)"
# 1) the two missing fault trajectories (sequential, ~30-60s each)
python3 capture_traj.py iv18 ilc11_8 >/tmp/captraj.log 2>&1
echo "trajectories done $(date)"
# 2) Monte Carlo distributions, 4 tubes in parallel (~30 min)
for tb in ilc11_7 iv6 iv18 ilc11_8; do
  TUBE=$tb python3 mc_distributions.py >/tmp/mcd_$tb.log 2>&1 &
done
wait
echo "ALL DONE $(date)"
touch /tmp/finish_DONE
