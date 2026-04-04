# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Contracts::Models::Clone do
  subject(:contract) { described_class.new }

  describe "#call" do
    let :attributes do
      {
        model_id: 1,
        model: {
          name: "test",
          label: "Test",
          description: nil,
          mime_type: "image/png",
          colors: 2,
          bit_depth: 1,
          rotation: 0,
          offset_x: 0,
          offset_y: 0,
          scale_factor: 1,
          width: 800,
          height: 480,
          palette_names: "bw",
          css: "{}"
        }
      }
    end

    it_behaves_like "a model contract"
  end
end
