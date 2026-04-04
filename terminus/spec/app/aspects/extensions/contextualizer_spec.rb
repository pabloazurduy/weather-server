# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Aspects::Extensions::Contextualizer, :db do
  subject(:contextualizer) { described_class.new }

  using Refinements::Hash

  describe "#call" do
    let :extension do
      Factory.structs[
        :extension,
        fields: [{"keyname" => "one", "default" => 1}],
        data: {"label" => "Test"}
      ]
    end

    let(:model) { Factory[:model, name: "test", css: {"classes" => {"size" => "screen--lg"}}] }
    let(:device) { Factory[:device, model_id: model.id] }
    let(:sensor) { Factory[:device_sensor, device_id: device.id] }

    it "answers all attributes" do
      sensor

      expect(contextualizer.call(extension, model_id: model.id, device_id: device.id)).to eq(
        "extension" => {
          "data" => {"label" => "Test"},
          "fields" => [{"keyname" => "one", "default" => 1}],
          "values" => {"one" => 1},
          "css_classes" => "screen screen--test screen--1bit screen--landscape " \
                           "screen--lg screen--1x"
        },
        "sensors" => [
          {
            "device_id" => device.id,
            "kind" => "temperature",
            "make" => "ACME",
            "model" => "Test",
            "unit" => "celcius",
            "value" => 20.1,
            "source" => "device",
            "created_at" => Time.new(2025, 1, 1).utc
          }
        ]
      )
    end

    it "answers attributes without fields, values, model, and sensors" do
      extension = Factory.structs[:extension]

      expect(contextualizer.call(extension)).to eq(
        "extension" => {"css_classes" => nil, "data" => {}, "fields" => [], "values" => {}},
        "sensors" => []
      )
    end
  end
end
