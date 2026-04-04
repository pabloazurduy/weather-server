# auto_register: false
# frozen_string_literal: true

module Terminus
  module Contracts
    module Rules
      SleepStartAt = lambda do
        stop_at = values.dig :device, :sleep_stop_at

        if value && stop_at.nil? then key.failure "must have corresponding stop time"
        elsif value.nil? && stop_at then key.failure "must be filled"
        else next
        end
      end
    end
  end
end
