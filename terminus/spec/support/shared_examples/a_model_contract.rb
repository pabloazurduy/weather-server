# frozen_string_literal: true

RSpec.shared_examples "a model contract" do
  it "answers success when valid" do
    expect(contract.call(attributes)).to be_success
  end

  it "answers failure when mime type is invalid" do
    attributes[:model][:mime_type] = "bogus/danger"

    expect(contract.call(attributes).errors.to_h).to eq(
      model: {
        mime_type: ["must be an image"]
      }
    )
  end
end
