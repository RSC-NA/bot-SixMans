from .sixMans import SixMans


async def setup(bot):
    await bot.add_cog(SixMans(bot))

