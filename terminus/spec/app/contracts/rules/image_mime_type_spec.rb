# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Contracts::Rules::ImageMimeType do
  subject(:contract) { simulation.new }

  let :simulation do
    implementation = described_class

    Class.new Dry::Validation::Contract do
      params { required(:model).hash { required(:mime_type).filled :string } }

      rule(model: :mime_type, &implementation)
    end
  end

  describe "#call" do
    let :attributes do
      {
        model: {
          mime_type: "image/png"
        }
      }
    end

    it "answers success with valid prefix" do
      result = contract.call attributes
      expect(result.success?).to be(true)
    end

    context "with invalid prefix" do
      let :result do
        attributes[:model][:mime_type] = "bogus/danger"
        contract.call attributes
      end

      it "answers failure" do
        expect(result.failure?).to be(true)
      end

      it "answers failure message" do
        expect(result.errors.to_h).to eq(model: {mime_type: ["must be an image"]})
      end
    end
  end
end
