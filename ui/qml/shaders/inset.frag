#version 440
layout(location=0) in vec2 qt_TexCoord0;
layout(location=0) out vec4 fragColor;
layout(std140,binding=0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 size;
    float cornerRadius;
    float depth;
};
float box(vec2 p,vec2 b,float r) {
    vec2 q=abs(p)-b+vec2(r);
    return length(max(q,vec2(0)))+min(max(q.x,q.y),0.0)-r;
}
void main() {
    vec2 p=qt_TexCoord0*size-size*.5;
    vec2 b=size*.5;
    float radius=min(cornerRadius,min(b.x,b.y));
    float d=box(p,b,radius);
    float mask=1.0-smoothstep(-1.,0.,d);
    float dark=smoothstep(-depth*2.,depth,box(p-vec2(depth),b,radius));
    float light=smoothstep(-depth*2.,depth,box(p+vec2(depth),b,radius));
    vec3 color=vec3(20./255.)*(1.-.78*dark)+vec3(75./255.)*.10*light;
    fragColor=vec4(color*mask,mask)*qt_Opacity;
}
