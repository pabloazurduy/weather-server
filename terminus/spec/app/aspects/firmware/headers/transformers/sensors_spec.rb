# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Aspects::Firmware::Headers::Transformers::Sensors do
  subject(:parser) { described_class.new }

  describe "#call" do
    it "answers records hash" do
      headers = {
        HTTP_SENSORS: <<~VALUE.delete("\n")
          make=Sensirion;model=SCD41;kind=humidity;value=26;unit=percent;created_at=1735714800,
          make=Sensirion;model=SCD41;kind=temperature;value=20.10;unit=celcius;created_at=1735714800
        VALUE
      }

      expect(parser.call(headers)).to be_success(
        HTTP_SENSORS: [
          {
            make: "Sensirion",
            model: "SCD41",
            kind: "humidity",
            value: "26",
            unit: "percent",
            source: "device",
            created_at: Time.at(1735714800)
          },
          {
            make: "Sensirion",
            model: "SCD41",
            kind: "temperature",
            value: "20.10",
            unit: "celcius",
            source: "device",
            created_at: Time.at(1735714800)
          }
        ]
      )
    end

    it "answers partial records with only single key and value" do
      headers = {HTTP_SENSORS: "make=Sensirion"}

      expect(parser.call(headers)).to be_success(
        HTTP_SENSORS: [{make: "Sensirion", source: "device"}]
      )
    end

    it "answers empty array when no key/value pairs exist" do
      expect(parser.call({HTTP_SENSORS: "make"})).to be_success(HTTP_SENSORS: [])
    end

    it "answers empty array when blank" do
      expect(parser.call({HTTP_SENSORS: ""})).to be_success(HTTP_SENSORS: [])
    end

    it "answers empty array when nil" do
      expect(parser.call({HTTP_SENSORS: nil})).to be_success(HTTP_SENSORS: [])
    end
  end
end
