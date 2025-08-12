from commands.music import play, now, queue, shuffle, clear
from commands.utility import join, leave, announce, jointo,help

async def register_commands(bot):
    bot.tree.add_command(play.slash_play)
    bot.tree.add_command(now.now_playing)
    bot.tree.add_command(queue.show_queue)
    bot.tree.add_command(shuffle.shuffle_queue)
    bot.tree.add_command(clear.clear_queue)
    bot.tree.add_command(join.join)
    bot.tree.add_command(leave.leave)
    bot.tree.add_command(announce.announce)
    bot.tree.add_command(jointo.jointo)
    bot.tree.add_command(help.help_command)