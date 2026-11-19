local STATE_END_WALK = 5
local STATE_DEAD     = 11

function check_done()
    -- Level completed
    if data.player_state == STATE_END_WALK then
        return true
    end
    -- Game over
    if data.lives < 2 then
        return true
    end
    
    return false
end