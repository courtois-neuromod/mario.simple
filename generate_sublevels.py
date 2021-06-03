#!/bin/env python

import retro

env = retro.make('SuperMarioBros-Nes','Level1-1',inttype=retro.data.Integrations.CUSTOM)
env.reset()

for world in range(8):
    env.data.set_value('levelHi', world)
    for stage in range(4):
        env.data.set_value('levelLo', stage)
        env.data.save(f"SuperMarioBros-Nes/Level{world+1}-{stage+1}.state")
