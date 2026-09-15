
import json
import os
import struct
import subprocess
import pytest

PIPELINE = "/app/pipeline.py"
SHADERS_DIR = "/app/shaders"

SPIRV_MAGIC = 0x07230203


def run_pipeline(input_glsl, output_dir):
    """Run the pipeline and return (metadata_dict, output_dir)."""
    result = subprocess.run(
        ["python3", PIPELINE, input_glsl, output_dir],
        capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"Pipeline failed on {input_glsl}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    meta_path = os.path.join(output_dir, "metadata.json")
    assert os.path.isfile(meta_path), "metadata.json not produced"
    with open(meta_path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def particles_result(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("particles_out"))
    meta = run_pipeline(os.path.join(SHADERS_DIR, "particles.glsl"), out)
    return meta, out


@pytest.fixture(scope="module")
def scene_result(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("scene_out"))
    meta = run_pipeline(os.path.join(SHADERS_DIR, "scene.glsl"), out)
    return meta, out


# ============================================================
# SPIR-V output tests — verify bytecode files exist and are valid
# ============================================================

class TestSPIRVParticles:
    def test_render_vs_spv_exists(self, particles_result):
        _, out = particles_result
        assert os.path.isfile(os.path.join(out, "particle_render", "vs.spv"))

    def test_render_fs_spv_exists(self, particles_result):
        _, out = particles_result
        assert os.path.isfile(os.path.join(out, "particle_render", "fs.spv"))

    def test_update_cs_spv_exists(self, particles_result):
        _, out = particles_result
        assert os.path.isfile(os.path.join(out, "particle_update", "cs.spv"))

    def test_render_vs_spv_magic(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "vs.spv"), "rb") as f:
            data = f.read(4)
        assert len(data) == 4
        magic = struct.unpack("<I", data)[0]
        assert magic == SPIRV_MAGIC, f"Bad SPIR-V magic: {hex(magic)}"

    def test_render_fs_spv_magic(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "fs.spv"), "rb") as f:
            magic = struct.unpack("<I", f.read(4))[0]
        assert magic == SPIRV_MAGIC

    def test_update_cs_spv_magic(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_update", "cs.spv"), "rb") as f:
            magic = struct.unpack("<I", f.read(4))[0]
        assert magic == SPIRV_MAGIC


class TestSPIRVScene:
    def test_textured_vs_spv(self, scene_result):
        _, out = scene_result
        assert os.path.isfile(os.path.join(out, "scene_textured", "vs.spv"))

    def test_textured_fs_spv(self, scene_result):
        _, out = scene_result
        assert os.path.isfile(os.path.join(out, "scene_textured", "fs.spv"))

    def test_flat_vs_spv(self, scene_result):
        _, out = scene_result
        assert os.path.isfile(os.path.join(out, "scene_flat", "vs.spv"))

    def test_flat_fs_spv(self, scene_result):
        _, out = scene_result
        assert os.path.isfile(os.path.join(out, "scene_flat", "fs.spv"))

    def test_frustum_cull_cs_spv(self, scene_result):
        _, out = scene_result
        assert os.path.isfile(os.path.join(out, "frustum_cull", "cs.spv"))

    def test_frustum_cull_cs_magic(self, scene_result):
        _, out = scene_result
        with open(os.path.join(out, "frustum_cull", "cs.spv"), "rb") as f:
            magic = struct.unpack("<I", f.read(4))[0]
        assert magic == SPIRV_MAGIC

    def test_textured_vs_spv_magic(self, scene_result):
        _, out = scene_result
        with open(os.path.join(out, "scene_textured", "vs.spv"), "rb") as f:
            magic = struct.unpack("<I", f.read(4))[0]
        assert magic == SPIRV_MAGIC


# ============================================================
# Metal output tests — verify MSL files contain expected constructs
# ============================================================

class TestMSLParticles:
    def test_render_vs_metal_exists(self, particles_result):
        _, out = particles_result
        assert os.path.isfile(os.path.join(out, "particle_render", "vs.metal"))

    def test_render_fs_metal_exists(self, particles_result):
        _, out = particles_result
        assert os.path.isfile(os.path.join(out, "particle_render", "fs.metal"))

    def test_update_cs_metal_exists(self, particles_result):
        _, out = particles_result
        assert os.path.isfile(os.path.join(out, "particle_update", "cs.metal"))

    def test_vs_metal_has_metal_header(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "vs.metal")) as f:
            content = f.read()
        assert "metal_stdlib" in content or "using namespace metal" in content

    def test_vs_metal_has_vertex_entry(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "vs.metal")) as f:
            content = f.read()
        # spirv-cross marks vertex entry points with 'vertex' keyword
        assert "vertex " in content

    def test_fs_metal_has_fragment_entry(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "fs.metal")) as f:
            content = f.read()
        assert "fragment " in content

    def test_cs_metal_has_kernel_entry(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_update", "cs.metal")) as f:
            content = f.read()
        assert "kernel " in content

    def test_fs_metal_has_texture_type(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "fs.metal")) as f:
            content = f.read()
        assert "texture2d" in content

    def test_vs_metal_has_device_buffer(self, particles_result):
        """Vertex shader reads from storage buffer — must have 'device' qualifier in Metal."""
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "vs.metal")) as f:
            content = f.read()
        assert "device " in content or "device\n" in content or "const device" in content


class TestMSLScene:
    def test_textured_vs_metal_vertex(self, scene_result):
        _, out = scene_result
        with open(os.path.join(out, "scene_textured", "vs.metal")) as f:
            content = f.read()
        assert "vertex " in content

    def test_textured_fs_metal_fragment(self, scene_result):
        _, out = scene_result
        with open(os.path.join(out, "scene_textured", "fs.metal")) as f:
            content = f.read()
        assert "fragment " in content

    def test_textured_fs_metal_texture(self, scene_result):
        _, out = scene_result
        with open(os.path.join(out, "scene_textured", "fs.metal")) as f:
            content = f.read()
        assert "texture2d" in content

    def test_frustum_cull_cs_metal_kernel(self, scene_result):
        _, out = scene_result
        with open(os.path.join(out, "frustum_cull", "cs.metal")) as f:
            content = f.read()
        assert "kernel " in content

    def test_flat_fs_metal_device(self, scene_result):
        """scene_flat FS reads from readonly storage buffer — device qualifier."""
        _, out = scene_result
        with open(os.path.join(out, "scene_flat", "fs.metal")) as f:
            content = f.read()
        assert "device " in content or "const device" in content


# ============================================================
# HLSL output tests — verify HLSL files contain expected constructs
# ============================================================

class TestHLSLParticles:
    def test_render_vs_hlsl_exists(self, particles_result):
        _, out = particles_result
        assert os.path.isfile(os.path.join(out, "particle_render", "vs.hlsl"))

    def test_render_fs_hlsl_exists(self, particles_result):
        _, out = particles_result
        assert os.path.isfile(os.path.join(out, "particle_render", "fs.hlsl"))

    def test_update_cs_hlsl_exists(self, particles_result):
        _, out = particles_result
        assert os.path.isfile(os.path.join(out, "particle_update", "cs.hlsl"))

    def test_vs_hlsl_has_cbuffer(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "vs.hlsl")) as f:
            content = f.read()
        assert "cbuffer" in content or "ConstantBuffer" in content

    def test_vs_hlsl_has_structured_buffer(self, particles_result):
        """VS reads readonly storage buffer — StructuredBuffer or ByteAddressBuffer."""
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "vs.hlsl")) as f:
            content = f.read()
        assert "StructuredBuffer" in content or "ByteAddressBuffer" in content

    def test_fs_hlsl_has_texture(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "fs.hlsl")) as f:
            content = f.read()
        assert "Texture2D" in content

    def test_fs_hlsl_has_sampler(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "fs.hlsl")) as f:
            content = f.read()
        assert "SamplerState" in content or "sampler" in content.lower()

    def test_cs_hlsl_has_rw_buffer(self, particles_result):
        """Compute shader has readwrite buffer — RWStructuredBuffer or RWByteAddressBuffer."""
        _, out = particles_result
        with open(os.path.join(out, "particle_update", "cs.hlsl")) as f:
            content = f.read()
        assert "RWStructuredBuffer" in content or "RWByteAddressBuffer" in content

    def test_cs_hlsl_has_readonly_buffer(self, particles_result):
        _, out = particles_result
        with open(os.path.join(out, "particle_update", "cs.hlsl")) as f:
            content = f.read()
        # The readonly ssbo_in should become StructuredBuffer (not RW)
        has_ro = "StructuredBuffer" in content or "ByteAddressBuffer" in content
        assert has_ro


class TestHLSLScene:
    def test_textured_fs_texture(self, scene_result):
        _, out = scene_result
        with open(os.path.join(out, "scene_textured", "fs.hlsl")) as f:
            content = f.read()
        assert "Texture2D" in content

    def test_textured_fs_sampler(self, scene_result):
        _, out = scene_result
        with open(os.path.join(out, "scene_textured", "fs.hlsl")) as f:
            content = f.read()
        assert "SamplerState" in content or "sampler" in content.lower()

    def test_frustum_cull_rw_buffer(self, scene_result):
        _, out = scene_result
        with open(os.path.join(out, "frustum_cull", "cs.hlsl")) as f:
            content = f.read()
        assert "RWStructuredBuffer" in content or "RWByteAddressBuffer" in content

    def test_flat_fs_readonly_buffer(self, scene_result):
        """scene_flat FS has readonly storage buffer."""
        _, out = scene_result
        with open(os.path.join(out, "scene_flat", "fs.hlsl")) as f:
            content = f.read()
        has_ro = "StructuredBuffer" in content or "ByteAddressBuffer" in content
        assert has_ro


# ============================================================
# Metadata structure tests
# ============================================================

class TestParticlesMetadata:
    def test_has_programs(self, particles_result):
        meta, _ = particles_result
        assert "programs" in meta

    def test_program_count(self, particles_result):
        meta, _ = particles_result
        assert len(meta["programs"]) == 2

    def test_particle_render_exists(self, particles_result):
        meta, _ = particles_result
        assert "particle_render" in meta["programs"]

    def test_particle_update_exists(self, particles_result):
        meta, _ = particles_result
        assert "particle_update" in meta["programs"]

    def test_particle_render_type(self, particles_result):
        meta, _ = particles_result
        assert meta["programs"]["particle_render"]["type"] == "render"

    def test_particle_update_type(self, particles_result):
        meta, _ = particles_result
        assert meta["programs"]["particle_update"]["type"] == "compute"

    def test_particle_render_stages(self, particles_result):
        meta, _ = particles_result
        stages = meta["programs"]["particle_render"]["stages"]
        assert "vs" in stages and "fs" in stages

    def test_particle_update_stages(self, particles_result):
        meta, _ = particles_result
        stages = meta["programs"]["particle_update"]["stages"]
        assert "cs" in stages

    def test_particle_render_stage_info(self, particles_result):
        meta, _ = particles_result
        si = meta["programs"]["particle_render"]["stage_info"]
        assert "vs" in si and "fs" in si

    def test_particle_update_stage_info(self, particles_result):
        meta, _ = particles_result
        si = meta["programs"]["particle_update"]["stage_info"]
        assert "cs" in si


class TestSceneMetadata:
    def test_program_count(self, scene_result):
        meta, _ = scene_result
        assert len(meta["programs"]) == 3

    def test_scene_textured_exists(self, scene_result):
        meta, _ = scene_result
        assert "scene_textured" in meta["programs"]

    def test_scene_flat_exists(self, scene_result):
        meta, _ = scene_result
        assert "scene_flat" in meta["programs"]

    def test_frustum_cull_exists(self, scene_result):
        meta, _ = scene_result
        assert "frustum_cull" in meta["programs"]

    def test_scene_textured_type(self, scene_result):
        meta, _ = scene_result
        assert meta["programs"]["scene_textured"]["type"] == "render"

    def test_scene_flat_type(self, scene_result):
        meta, _ = scene_result
        assert meta["programs"]["scene_flat"]["type"] == "render"

    def test_frustum_cull_type(self, scene_result):
        meta, _ = scene_result
        assert meta["programs"]["frustum_cull"]["type"] == "compute"

    def test_scene_textured_stages(self, scene_result):
        meta, _ = scene_result
        stages = meta["programs"]["scene_textured"]["stages"]
        assert "vs" in stages and "fs" in stages

    def test_frustum_cull_stages(self, scene_result):
        meta, _ = scene_result
        assert "cs" in meta["programs"]["frustum_cull"]["stages"]


# ============================================================
# Resource reflection tests — particle_render
# ============================================================

class TestParticleRenderResources:
    def _res(self, particles_result):
        meta, _ = particles_result
        return meta["programs"]["particle_render"]["resources"]

    def test_ub_count(self, particles_result):
        assert len(self._res(particles_result)["uniform_blocks"]) == 2

    def test_sb_count(self, particles_result):
        assert len(self._res(particles_result)["storage_buffers"]) == 1

    def test_tex_count(self, particles_result):
        assert len(self._res(particles_result)["textures"]) == 2

    def test_smp_count(self, particles_result):
        assert len(self._res(particles_result)["samplers"]) == 1

    def test_vs_params_present(self, particles_result):
        names = [u["name"] for u in self._res(particles_result)["uniform_blocks"]]
        assert "vs_params" in names

    def test_fs_params_present(self, particles_result):
        names = [u["name"] for u in self._res(particles_result)["uniform_blocks"]]
        assert "fs_params" in names

    def test_vs_params_stage(self, particles_result):
        ub = [u for u in self._res(particles_result)["uniform_blocks"]
              if u["name"] == "vs_params"][0]
        assert ub["stage"] == "vs"

    def test_vs_params_slot(self, particles_result):
        ub = [u for u in self._res(particles_result)["uniform_blocks"]
              if u["name"] == "vs_params"][0]
        assert ub["slot"] == 0

    def test_fs_params_stage(self, particles_result):
        ub = [u for u in self._res(particles_result)["uniform_blocks"]
              if u["name"] == "fs_params"][0]
        assert ub["stage"] == "fs"

    def test_fs_params_slot(self, particles_result):
        ub = [u for u in self._res(particles_result)["uniform_blocks"]
              if u["name"] == "fs_params"][0]
        assert ub["slot"] == 1

    def test_ssbo_particles_name(self, particles_result):
        names = [s["name"] for s in self._res(particles_result)["storage_buffers"]]
        assert "ssbo_particles" in names

    def test_ssbo_particles_readonly(self, particles_result):
        sb = [s for s in self._res(particles_result)["storage_buffers"]
              if s["name"] == "ssbo_particles"][0]
        assert sb["readonly"] is True

    def test_ssbo_particles_stage(self, particles_result):
        sb = [s for s in self._res(particles_result)["storage_buffers"]
              if s["name"] == "ssbo_particles"][0]
        assert sb["stage"] == "vs"

    def test_ssbo_particles_slot(self, particles_result):
        sb = [s for s in self._res(particles_result)["storage_buffers"]
              if s["name"] == "ssbo_particles"][0]
        assert sb["slot"] == 0

    def test_diffuse_tex_present(self, particles_result):
        names = [t["name"] for t in self._res(particles_result)["textures"]]
        assert "diffuse_tex" in names

    def test_normal_tex_present(self, particles_result):
        names = [t["name"] for t in self._res(particles_result)["textures"]]
        assert "normal_tex" in names

    def test_diffuse_tex_stage(self, particles_result):
        tex = [t for t in self._res(particles_result)["textures"]
               if t["name"] == "diffuse_tex"][0]
        assert tex["stage"] == "fs"

    def test_diffuse_tex_slot(self, particles_result):
        tex = [t for t in self._res(particles_result)["textures"]
               if t["name"] == "diffuse_tex"][0]
        assert tex["slot"] == 1

    def test_normal_tex_slot(self, particles_result):
        tex = [t for t in self._res(particles_result)["textures"]
               if t["name"] == "normal_tex"][0]
        assert tex["slot"] == 2

    def test_tex_smp_present(self, particles_result):
        names = [s["name"] for s in self._res(particles_result)["samplers"]]
        assert "tex_smp" in names

    def test_tex_smp_stage(self, particles_result):
        smp = [s for s in self._res(particles_result)["samplers"]
               if s["name"] == "tex_smp"][0]
        assert smp["stage"] == "fs"

    def test_tex_smp_slot(self, particles_result):
        smp = [s for s in self._res(particles_result)["samplers"]
               if s["name"] == "tex_smp"][0]
        assert smp["slot"] == 0


# ============================================================
# Resource reflection tests — particle_update
# ============================================================

class TestParticleUpdateResources:
    def _res(self, particles_result):
        meta, _ = particles_result
        return meta["programs"]["particle_update"]["resources"]

    def test_ub_count(self, particles_result):
        assert len(self._res(particles_result)["uniform_blocks"]) == 1

    def test_sb_count(self, particles_result):
        assert len(self._res(particles_result)["storage_buffers"]) == 2

    def test_tex_count(self, particles_result):
        assert len(self._res(particles_result)["textures"]) == 0

    def test_smp_count(self, particles_result):
        assert len(self._res(particles_result)["samplers"]) == 0

    def test_cs_params_name(self, particles_result):
        ubs = self._res(particles_result)["uniform_blocks"]
        assert ubs[0]["name"] == "cs_params"

    def test_cs_params_stage(self, particles_result):
        ubs = self._res(particles_result)["uniform_blocks"]
        assert ubs[0]["stage"] == "cs"

    def test_cs_params_slot(self, particles_result):
        ubs = self._res(particles_result)["uniform_blocks"]
        assert ubs[0]["slot"] == 0

    def test_ssbo_in_present(self, particles_result):
        names = [s["name"] for s in self._res(particles_result)["storage_buffers"]]
        assert "ssbo_in" in names

    def test_ssbo_out_present(self, particles_result):
        names = [s["name"] for s in self._res(particles_result)["storage_buffers"]]
        assert "ssbo_out" in names

    def test_ssbo_in_readonly(self, particles_result):
        sb = [s for s in self._res(particles_result)["storage_buffers"]
              if s["name"] == "ssbo_in"][0]
        assert sb["readonly"] is True

    def test_ssbo_out_readwrite(self, particles_result):
        sb = [s for s in self._res(particles_result)["storage_buffers"]
              if s["name"] == "ssbo_out"][0]
        assert sb["readonly"] is False


# ============================================================
# Resource reflection tests — scene programs
# ============================================================

class TestSceneTexturedResources:
    def _res(self, scene_result):
        meta, _ = scene_result
        return meta["programs"]["scene_textured"]["resources"]

    def test_ub_count(self, scene_result):
        assert len(self._res(scene_result)["uniform_blocks"]) == 2

    def test_sb_count(self, scene_result):
        assert len(self._res(scene_result)["storage_buffers"]) == 0

    def test_tex_count(self, scene_result):
        assert len(self._res(scene_result)["textures"]) == 3

    def test_smp_count(self, scene_result):
        assert len(self._res(scene_result)["samplers"]) == 2

    def test_vs_uniforms_present(self, scene_result):
        names = [u["name"] for u in self._res(scene_result)["uniform_blocks"]]
        assert "vs_uniforms" in names

    def test_fs_material_present(self, scene_result):
        names = [u["name"] for u in self._res(scene_result)["uniform_blocks"]]
        assert "fs_material" in names

    def test_albedo_tex_present(self, scene_result):
        names = [t["name"] for t in self._res(scene_result)["textures"]]
        assert "albedo_tex" in names

    def test_metallic_roughness_tex_present(self, scene_result):
        names = [t["name"] for t in self._res(scene_result)["textures"]]
        assert "metallic_roughness_tex" in names

    def test_emissive_tex_present(self, scene_result):
        names = [t["name"] for t in self._res(scene_result)["textures"]]
        assert "emissive_tex" in names

    def test_material_smp_present(self, scene_result):
        names = [s["name"] for s in self._res(scene_result)["samplers"]]
        assert "material_smp" in names

    def test_emissive_smp_present(self, scene_result):
        names = [s["name"] for s in self._res(scene_result)["samplers"]]
        assert "emissive_smp" in names


class TestSceneFlatResources:
    def _res(self, scene_result):
        meta, _ = scene_result
        return meta["programs"]["scene_flat"]["resources"]

    def test_ub_count(self, scene_result):
        assert len(self._res(scene_result)["uniform_blocks"]) == 2

    def test_sb_count(self, scene_result):
        assert len(self._res(scene_result)["storage_buffers"]) == 1

    def test_tex_count(self, scene_result):
        assert len(self._res(scene_result)["textures"]) == 0

    def test_smp_count(self, scene_result):
        assert len(self._res(scene_result)["samplers"]) == 0

    def test_vs_uniforms_present(self, scene_result):
        names = [u["name"] for u in self._res(scene_result)["uniform_blocks"]]
        assert "vs_uniforms" in names

    def test_fs_flat_material_present(self, scene_result):
        names = [u["name"] for u in self._res(scene_result)["uniform_blocks"]]
        assert "fs_flat_material" in names

    def test_ssbo_color_table_present(self, scene_result):
        names = [s["name"] for s in self._res(scene_result)["storage_buffers"]]
        assert "ssbo_color_table" in names

    def test_ssbo_color_table_readonly(self, scene_result):
        sb = [s for s in self._res(scene_result)["storage_buffers"]
              if s["name"] == "ssbo_color_table"][0]
        assert sb["readonly"] is True

    def test_ssbo_color_table_stage(self, scene_result):
        sb = [s for s in self._res(scene_result)["storage_buffers"]
              if s["name"] == "ssbo_color_table"][0]
        assert sb["stage"] == "fs"


class TestFrustumCullResources:
    def _res(self, scene_result):
        meta, _ = scene_result
        return meta["programs"]["frustum_cull"]["resources"]

    def test_ub_count(self, scene_result):
        assert len(self._res(scene_result)["uniform_blocks"]) == 1

    def test_sb_count(self, scene_result):
        assert len(self._res(scene_result)["storage_buffers"]) == 3

    def test_tex_count(self, scene_result):
        assert len(self._res(scene_result)["textures"]) == 0

    def test_smp_count(self, scene_result):
        assert len(self._res(scene_result)["samplers"]) == 0

    def test_cull_params_name(self, scene_result):
        ubs = self._res(scene_result)["uniform_blocks"]
        assert ubs[0]["name"] == "cull_params"

    def test_cull_params_stage(self, scene_result):
        ubs = self._res(scene_result)["uniform_blocks"]
        assert ubs[0]["stage"] == "cs"

    def test_ssbo_aabbs_readonly(self, scene_result):
        sb = [s for s in self._res(scene_result)["storage_buffers"]
              if s["name"] == "ssbo_aabbs"][0]
        assert sb["readonly"] is True

    def test_ssbo_draw_cmds_readwrite(self, scene_result):
        sb = [s for s in self._res(scene_result)["storage_buffers"]
              if s["name"] == "ssbo_draw_cmds"][0]
        assert sb["readonly"] is False

    def test_ssbo_visible_count_readwrite(self, scene_result):
        sb = [s for s in self._res(scene_result)["storage_buffers"]
              if s["name"] == "ssbo_visible_count"][0]
        assert sb["readonly"] is False


# ============================================================
# Stage info path tests
# ============================================================

class TestStageInfoPaths:
    def test_particle_render_vs_paths(self, particles_result):
        meta, _ = particles_result
        si = meta["programs"]["particle_render"]["stage_info"]["vs"]
        assert "spirv_path" in si
        assert si["spirv_path"].endswith("vs.spv")
        assert si["metal_path"].endswith("vs.metal")
        assert si["hlsl_path"].endswith("vs.hlsl")

    def test_particle_render_fs_paths(self, particles_result):
        meta, _ = particles_result
        si = meta["programs"]["particle_render"]["stage_info"]["fs"]
        assert si["spirv_path"].endswith("fs.spv")
        assert si["metal_path"].endswith("fs.metal")
        assert si["hlsl_path"].endswith("fs.hlsl")

    def test_particle_update_cs_paths(self, particles_result):
        meta, _ = particles_result
        si = meta["programs"]["particle_update"]["stage_info"]["cs"]
        assert si["spirv_path"].endswith("cs.spv")
        assert si["metal_path"].endswith("cs.metal")
        assert si["hlsl_path"].endswith("cs.hlsl")

    def test_scene_textured_stage_info_keys(self, scene_result):
        meta, _ = scene_result
        si = meta["programs"]["scene_textured"]["stage_info"]
        assert "vs" in si and "fs" in si

    def test_frustum_cull_stage_info_keys(self, scene_result):
        meta, _ = scene_result
        si = meta["programs"]["frustum_cull"]["stage_info"]
        assert "cs" in si

    def test_entry_points(self, particles_result):
        meta, _ = particles_result
        for prog in meta["programs"].values():
            for stage_info in prog["stage_info"].values():
                assert stage_info["entry_point"] == "main"


# ============================================================
# @include_block expansion tests — verify shared types in output
# ============================================================

class TestIncludeBlockExpansion:
    def test_particle_struct_in_vs_metal(self, particles_result):
        """particle_t from @block shared_types must appear in VS Metal output."""
        _, out = particles_result
        with open(os.path.join(out, "particle_render", "vs.metal")) as f:
            content = f.read()
        # spirv-cross produces struct fields in the output
        assert "pos" in content and "vel" in content and "color" in content

    def test_particle_struct_in_cs_metal(self, particles_result):
        """particle_t from @block shared_types must appear in CS Metal output."""
        _, out = particles_result
        with open(os.path.join(out, "particle_update", "cs.metal")) as f:
            content = f.read()
        assert "pos" in content and "vel" in content

    def test_material_struct_in_textured_fs_hlsl(self, scene_result):
        """material_t from @block material_types must appear in textured FS HLSL."""
        _, out = scene_result
        with open(os.path.join(out, "scene_textured", "fs.hlsl")) as f:
            content = f.read()
        assert "base_color" in content or "metallic" in content

    def test_material_struct_in_flat_fs_hlsl(self, scene_result):
        """material_t from @block material_types must also appear in flat FS HLSL."""
        _, out = scene_result
        with open(os.path.join(out, "scene_flat", "fs.hlsl")) as f:
            content = f.read()
        assert "base_color" in content or "metallic" in content


# ============================================================
# Shared vertex shader tests
# ============================================================

class TestSharedVertexShader:
    """vs_scene is used in both scene_textured and scene_flat programs."""

    def test_both_programs_produce_vs_spv(self, scene_result):
        _, out = scene_result
        assert os.path.isfile(os.path.join(out, "scene_textured", "vs.spv"))
        assert os.path.isfile(os.path.join(out, "scene_flat", "vs.spv"))

    def test_both_programs_produce_vs_metal(self, scene_result):
        _, out = scene_result
        assert os.path.isfile(os.path.join(out, "scene_textured", "vs.metal"))
        assert os.path.isfile(os.path.join(out, "scene_flat", "vs.metal"))

    def test_both_programs_produce_vs_hlsl(self, scene_result):
        _, out = scene_result
        assert os.path.isfile(os.path.join(out, "scene_textured", "vs.hlsl"))
        assert os.path.isfile(os.path.join(out, "scene_flat", "vs.hlsl"))

    def test_vs_uniforms_in_both_programs(self, scene_result):
        meta, _ = scene_result
        for prog_name in ["scene_textured", "scene_flat"]:
            ubs = meta["programs"][prog_name]["resources"]["uniform_blocks"]
            names = [u["name"] for u in ubs]
            assert "vs_uniforms" in names, f"vs_uniforms missing from {prog_name}"

    def test_vs_uniforms_stage_consistent(self, scene_result):
        meta, _ = scene_result
        for prog_name in ["scene_textured", "scene_flat"]:
            ub = [u for u in meta["programs"][prog_name]["resources"]["uniform_blocks"]
                  if u["name"] == "vs_uniforms"][0]
            assert ub["stage"] == "vs"
            assert ub["slot"] == 0
