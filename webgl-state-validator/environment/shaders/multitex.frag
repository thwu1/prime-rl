#version 100
precision mediump float;
uniform sampler2D u_diffuse;
uniform samplerCube u_envmap;
varying vec2 v_texcoord;
varying vec3 v_reflect;
void main() {
    vec4 diffuse = texture2D(u_diffuse, v_texcoord);
    vec4 env = textureCube(u_envmap, v_reflect);
    gl_FragColor = mix(diffuse, env, 0.3);
}
