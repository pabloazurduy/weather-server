# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Schemas::Coercers::DefaultToFalse do
  subject(:coercer) { described_class }

  let(:attributes) { {display: true} }

  let :result do
    Dry::Schema::Result.new(attributes, message_compiler: proc { Hash.new }, result_ast: [])
  end

  describe "#call" do
    it "answers original attributes when present" do
      expect(coercer.call(:display, result)).to eq(display: true)
    end

    it "answers false when key is missing" do
      attributes.delete :display
      expect(coercer.call(:display, result)).to eq(display: false)
    end

    context "when attributes are nil" do
      let(:result) { Dry::Schema::Result.new nil, message_compiler: nil, result_ast: [] }

      it "answers nil" do
        expect(coercer.call(:display, result)).to be(nil)
      end
    end
  end
end
