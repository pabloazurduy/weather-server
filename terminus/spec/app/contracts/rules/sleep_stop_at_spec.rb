# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Contracts::Rules::SleepStopAt do
  subject(:contract) { simulation.new }

  let :simulation do
    implementation = described_class

    Class.new Dry::Validation::Contract do
      params do
        required(:device).hash do
          optional(:sleep_start_at).maybe :time
          optional(:sleep_stop_at).maybe :time
        end
      end

      rule(device: :sleep_stop_at, &implementation)
    end
  end

  describe "#call" do
    let :attributes do
      {
        device: {
          sleep_start_at: "01:00:00",
          sleep_stop_at: "02:00:00"
        }
      }
    end

    it "answers success with no errors" do
      result = contract.call attributes
      expect(result.success?).to be(true)
    end

    it "answers error when corresponding start is missing" do
      attributes[:device].delete :sleep_start_at
      result = contract.call attributes

      expect(result.errors.to_h).to eq(
        device: {
          sleep_stop_at: ["must have corresponding start time"]
        }
      )
    end

    it "answers error when stop isn't filled" do
      attributes[:device].delete :sleep_stop_at
      result = contract.call attributes

      expect(result.errors.to_h).to eq(device: {sleep_stop_at: ["must be filled"]})
    end
  end
end
