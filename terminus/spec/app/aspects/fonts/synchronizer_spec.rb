# frozen_string_literal: true

require "hanami_helper"
require "trmnl/api"

RSpec.describe Terminus::Aspects::Fonts::Synchronizer do
  using Refinements::Pathname

  subject(:synchronizer) { described_class.new downloader: }

  include_context "with application dependencies"

  let(:downloader) { instance_double Terminus::Aspects::Downloader, call: response }

  let :response do
    Success(
      HTTP::Response.new(
        uri: "https://trmnl-oss.s3-us-east-2.amazonaws.com/fonts/test.ttf",
        verb: :get,
        body: [123].pack("N"),
        status: 200,
        version: 1.0
      )
    )
  end

  describe "#call" do
    it "deletes unknown files" do
      temp_dir.join("test.txt").touch
      synchronizer.call

      expect(temp_dir.files).not_to include(temp_dir.join("test.txt"))
    end

    it "doesn't download files that exist" do
      downloader = instance_double Terminus::Aspects::Downloader, call: Failure("Skip.")
      synchronizer = described_class.new(downloader:)

      temp_dir.join("BlockKie.ttf").touch
      synchronizer.call

      expect(temp_dir.files).to contain_exactly(temp_dir.join("BlockKie.ttf"))
    end

    it "answers array of mixed results" do
      count = 0

      allow(downloader).to receive(:call) do
        count += 1
        count.odd? ? response : Failure("Danger!")
      end

      expect(synchronizer.call).to eq(
        [
          Success(temp_dir.join("BlockKie.ttf")),
          Failure("Danger!"),
          Success(temp_dir.join("dogicapixelbold.ttf")),
          Failure("Danger!"),
          Success(temp_dir.join("Inter.ttf")),
          Failure("Danger!"),
          Success(temp_dir.join("NicoClean-Regular.ttf")),
          Failure("Danger!")
        ]
      )
    end

    it "downloads remote files" do
      synchronizer.call

      expect(temp_dir.files).to eq(
        [
          temp_dir.join("BlockKie.ttf"),
          temp_dir.join("Inter-Italic.ttf"),
          temp_dir.join("Inter.ttf"),
          temp_dir.join("NicoBold-Regular.ttf"),
          temp_dir.join("NicoClean-Regular.ttf"),
          temp_dir.join("NicoPups-Regular.ttf"),
          temp_dir.join("dogicapixel.ttf"),
          temp_dir.join("dogicapixelbold.ttf")
        ]
      )
    end

    context "with failure" do
      subject(:synchronizer) { described_class.new names: ["test.ttf"], downloader: }

      let(:response) { Failure "Danger!" }

      it "answers message" do
        expect(synchronizer.call).to contain_exactly(Failure("Danger!"))
      end
    end
  end
end
