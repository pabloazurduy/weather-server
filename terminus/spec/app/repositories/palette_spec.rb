# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Repositories::Palette, :db do
  subject(:repository) { described_class.new }

  let(:palette) { Factory[:palette] }

  describe "#all" do
    it "answers all records by published date/time" do
      palette
      expect(repository.all.map(&:id)).to contain_exactly(palette.id)
    end

    it "answers empty array when records don't exist" do
      expect(repository.all).to eq([])
    end
  end

  describe "#delete_all" do
    it "answers all records for given attributes" do
      palette
      Factory[:palette, kind: "trmnl"]
      repository.delete_all kind: ["trmnl"]

      expect(repository.all.map(&:id)).to contain_exactly(palette.id)
    end

    it "answers number of records deleted" do
      palette
      Factory[:palette, kind: "trmnl"]

      expect(repository.delete_all).to eq(2)
    end

    it "answers zero when there is nothing to delete" do
      expect(repository.delete_all).to eq(0)
    end
  end

  describe "#find" do
    it "answers record by ID" do
      expect(repository.find(palette.id)).to eq(palette)
    end

    it "answers nil for unknown ID" do
      expect(repository.find(13)).to be(nil)
    end

    it "answers nil for nil ID" do
      expect(repository.find(nil)).to be(nil)
    end
  end

  describe "#find_by" do
    it "answers record when found by single attribute" do
      expect(repository.find_by(name: palette.name)).to eq(palette)
    end

    it "answers record when found by multiple attributes" do
      palette
      expect(repository.find_by(grays: 2, framework_class: "screen--1bit")).to eq(palette)
    end

    it "answers nil when not found" do
      expect(repository.find_by(name: "bogus")).to be(nil)
    end

    it "answers nil for nil" do
      expect(repository.find_by(name: nil)).to be(nil)
    end
  end

  describe "#search" do
    let(:palette) { Factory[:palette, label: "Test"] }

    before { palette }

    it "answers records for case insensitive value" do
      expect(repository.search(:label, "test")).to contain_exactly(have_attributes(label: "Test"))
    end

    it "answers records for partial value" do
      expect(repository.search(:label, "te")).to contain_exactly(have_attributes(label: "Test"))
    end

    it "answers empty array for invalid value" do
      expect(repository.search(:label, "bogus")).to eq([])
    end
  end

  describe "#where" do
    it "answers record for single attribute" do
      expect(repository.where(label: palette.label)).to contain_exactly(palette)
    end

    it "answers record for multiple attributes" do
      expect(repository.where(label: palette.label, name: palette.name)).to contain_exactly(palette)
    end

    it "answers empty array for unknown value" do
      expect(repository.where(label: "bogus")).to eq([])
    end

    it "answers empty array for nil" do
      expect(repository.where(label: nil)).to eq([])
    end
  end
end
