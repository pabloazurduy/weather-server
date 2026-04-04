# frozen_string_literal: true

RSpec.shared_examples "a sleep contract" do
  it "answers success when valid" do
    expect(contract.call(attributes)).to be_success
  end

  it "answers success when start and end date/time are nil" do
    attributes[:device].delete :sleep_start_at
    attributes[:device].delete :sleep_stop_at

    expect(contract.call(attributes)).to be_success
  end

  it "answers failures when start is missing but stop is present" do
    attributes[:device][:sleep_start_at] = nil

    expect(contract.call(attributes).errors.to_h).to eq(
      device: {
        sleep_start_at: ["must be filled"],
        sleep_stop_at: ["must have corresponding start time"]
      }
    )
  end

  it "answers failures when start is present but stop is missing" do
    attributes[:device][:sleep_stop_at] = nil

    expect(contract.call(attributes).errors.to_h).to eq(
      device: {
        sleep_start_at: ["must have corresponding stop time"],
        sleep_stop_at: ["must be filled"]
      }
    )
  end
end
