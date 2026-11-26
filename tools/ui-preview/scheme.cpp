#include "cpp/cam/hct.h"
#include "cpp/scheme/scheme_content.h"
#include <cstdio>
using namespace material_color_utilities;
#define P(n) printf("  --md-%s: #%06x;\n", #n, s.Get##n() & 0xffffff);
int main(int argc,char**argv){ bool dark=argc>1; SchemeContent s(Hct(0xffff3d8a), dark, 0.0);
P(Background)P(OnBackground)P(Surface)P(SurfaceDim)P(SurfaceBright)P(SurfaceContainerLowest)P(SurfaceContainerLow)P(SurfaceContainer)P(SurfaceContainerHigh)P(SurfaceContainerHighest)P(OnSurface)P(SurfaceVariant)P(OnSurfaceVariant)P(Outline)P(OutlineVariant)P(InverseSurface)P(InverseOnSurface)P(Primary)P(OnPrimary)P(PrimaryContainer)P(OnPrimaryContainer)P(Secondary)P(OnSecondary)P(SecondaryContainer)P(OnSecondaryContainer)P(Tertiary)P(OnTertiary)P(TertiaryContainer)P(OnTertiaryContainer)P(Error)P(OnError)P(ErrorContainer)P(OnErrorContainer)}
