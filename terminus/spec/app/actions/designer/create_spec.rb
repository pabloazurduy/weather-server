# frozen_string_literal: true

require "hanami_helper"

RSpec.describe Terminus::Actions::Designer::Create, :db do
  subject(:action) { described_class.new }

  include_context "with application dependencies"

  describe "#call" do
    let(:model) { Factory[:model, name: "og_png"] }
    let(:parameters) { {template: {name: :test, label: "Test", content: "<p>Test</p>"}} }
    let(:repository) { Terminus::Repositories::Screen.new }

    before { model }

    it "answers original content" do
      response = Rack::MockRequest.new(action).post "",
                                                    "HTTP_HX_REQUEST" => "true",
                                                    params: parameters
      expect(response.body).to eq("<p>Test</p>")
    end

    it "creates screen when none exists" do
      Rack::MockRequest.new(action).post "", "HTTP_HX_REQUEST" => "true", params: parameters

      expect(repository.find_by(name: "test")).to have_attributes(
        model_id: model.id,
        name: "test",
        label: "Test",
        image_attributes: hash_including(
          metadata: hash_including(
            size: kind_of(Integer),
            width: 800,
            height: 480,
            filename: "test.png",
            mime_type: "image/png"
          )
        )
      )
    end

    it "recreates screen when screen exists by same name" do
      Factory[:screen, model_id: model.id, name: "test", label: "Old"]
      Rack::MockRequest.new(action).post "", "HTTP_HX_REQUEST" => "true", params: parameters

      expect(repository.find_by(name: "test")).to have_attributes(
        model_id: model.id,
        name: "test",
        label: "Test"
      )
    end

    it "answers created status" do
      response = Rack::MockRequest.new(action).post "",
                                                    "HTTP_HX_REQUEST" => "true",
                                                    params: parameters

      expect(response.status).to eq(201)
    end

    it "renders show view when form is submitted" do
      response = Rack::MockRequest.new(action).post "", params: parameters
      expect(response.body).to include("Welcome to the Terminus designer!")
    end

    it "answers unprocessable content with invalid parameters" do
      parameters[:template].delete :name
      response = Rack::MockRequest.new(action).post "", params: parameters

      expect(response.status).to eq(422)
    end
  end
end
