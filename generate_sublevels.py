#!/bin/env python

import retro, gzip

env = retro.make('SuperMarioBros-Nes','Level1-1',inttype=retro.data.Integrations.CUSTOM)
env.reset()

for world in range(8):
    env.data.set_value('levelHi', world)
    for stage in range(4):
        env.data.set_value('levelLo', stage)
        env.reset()
        with gzip.open(f"SuperMarioBros-Nes/Level{world+1}-{stage+1}.state.tmp", 'wb') as fh:
            fh.write(env.initial_state)
