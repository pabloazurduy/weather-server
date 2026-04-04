# frozen_string_literal: true

RSpec::Matchers.define :match_device_friendly_id do
  match { |actual| actual.match?(/[A-F0-9]{6}/) }
end
