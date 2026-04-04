# auto_register: false
# frozen_string_literal: true

module Terminus
  module Contracts
    module Rules
      SleepStopAt = lambda do
        start_at = values.dig :device, :sleep_start_at

        if value && start_at.nil? then key.failure "must have corresponding start time"
        elsif value.nil? && start_at then key.failure "must be filled"
        else next
        end
      end
    end
  end
end
